"""Validate optical flow estimation performance on standard datasets."""

# =============================================================================
# Copyright 2021 Henrique Morimitsu
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =============================================================================

import pdb

import logging
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2 as cv
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
from tqdm import tqdm

import ptlflow
from ptlflow_attacked.ptlflow import get_model, get_model_reference
from ptlflow_attacked.ptlflow.models.base_model.base_model import BaseModel
from ptlflow_attacked.ptlflow.utils import flow_utils
from ptlflow_attacked.ptlflow.utils.io_adapter import IOAdapter
from ptlflow_attacked.ptlflow.utils.utils import (
    add_datasets_to_parser,
    config_logging,
    get_list_of_available_models_list,
    tensor_dict_to_numpy,
)

# Import cosPGD functions
from cospgd import functions as attack_functions
import torch.nn as nn
import ptlflow_attacked.adversarial_attacks_pytorch
from ptlflow_attacked.adversarial_attacks_pytorch.torchattacks import FGSM, FFGSM, APGD
# Attack parameters
epsilon = 0.03
norm = "two"
alpha = 0.01
iterations = 5
criterion = nn.CrossEntropyLoss(reduction="none")
targeted = False
batch_size = 1


config_logging()


def _init_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument(
        "model",
        type=str,
        choices=["all", "select"] + get_list_of_available_models_list(),
        help="Name of the model to use.",
    )
    parser.add_argument(
        "--attack",
        type=str,
        default="none",
        choices=["fgsm", "pgd", "cospgd", "ffgsm", "apgd", "none"],
        help="Name of the attack to use.",
    )
    parser.add_argument('-it', '--iterations', type=int, default=1,
                        help='number of iterations for adversarial attack')
    
    parser.add_argument(
        "--attack_norm",
        type=str,
        default=norm,
        choices=["two", "inf"],
        help="Set norm to use for adversarial attack.",
    )
    parser.add_argument(
        "--attack_epsilon",
        type=float,
        default=epsilon,
        help="Set epsilon to use for adversarial attack.",
    )
    parser.add_argument(
        "--attack_iterations",
        type=int,
        default=iterations,
        help="Set number of iterations for adversarial attack.",
    )
    parser.add_argument(
        "--attack_alpha",
        type=float,
        default=alpha,
        help="Set epsilon to use for adversarial attack.",
    )
    parser.add_argument(
        "--selection",
        type=str,
        nargs="+",
        default=None,
        help=(
            "Used in combination with model=select. The select mode can be used to run the validation on multiple models "
            "at once. Put a list of model names here separated by spaces."
        ),
    )
    parser.add_argument(
        "--exclude",
        type=str,
        nargs="+",
        default=None,
        help=(
            "Used in combination with model=all. A list of model names that will not be validated."
        ),
    )
    parser.add_argument(
        "--output_path",
        type=str,
        default=str(Path("outputs/validate")),
        help="Path to the directory where the validation results will be saved.",
    )
    parser.add_argument(
        "--write_outputs",
        action="store_true",
        help="If set, the estimated flow is saved to disk.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="If set, the results are shown on the screen.",
    )
    parser.add_argument(
        "--flow_format",
        type=str,
        default="original",
        choices=["flo", "png", "original"],
        help=(
            "The format to use when saving the estimated optical flow. If 'original', then the format will be the same "
            + "one the dataset uses for the groundtruth."
        ),
    )
    parser.add_argument(
        "--max_forward_side",
        type=int,
        default=None,
        help=(
            "If max(height, width) of the input image is larger than this value, then the image is downscaled "
            "before the forward and the outputs are bilinearly upscaled to the original resolution."
        ),
    )
    parser.add_argument(
        "--scale_factor",
        type=float,
        default=None,
        help=("Multiply the input image by this scale factor before forwarding."),
    )
    parser.add_argument(
        "--max_show_side",
        type=int,
        default=1000,
        help=(
            "If max(height, width) of the output image is larger than this value, then the image is downscaled "
            "before showing it on the screen."
        ),
    )
    parser.add_argument(
        "--max_samples",
        type=int,
        default=None,
        help=(
            "Maximum number of samples per dataset will be used for calculating the metrics."
        ),
    )
    parser.add_argument(
        "--reversed",
        action="store_true",
        help="To be combined with model all or select. Iterates over the list of models in reversed order",
    )
    parser.add_argument(
        "--warm_start",
        action="store_true",
        help="If set, stores the previous estimation to be used a starting point for prediction.",
    )
    parser.add_argument(
        "--fp16", action="store_true", help="If set, use half floating point precision."
    )
    parser.add_argument(
        "--seq_val_mode",
        type=str,
        default="all",
        choices=("all", "first", "middle", "last"),
        help=(
            "Used only when the model predicts outputs for more than one frame. Select which predictions will be used for evaluation."
        ),
    )
    parser.add_argument(
        "--write_individual_metrics",
        action="store_true",
        help="If set, save a table of metrics for every image.",
    )
    return parser


def generate_outputs(
    args: Namespace,
    inputs: Dict[str, torch.Tensor],
    preds: Dict[str, torch.Tensor],
    dataloader_name: str,
    batch_idx: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Display on screen and/or save outputs to disk, if required.

    Parameters
    ----------
    args : Namespace
        The arguments with the required values to manage the outputs.
    inputs : Dict[str, torch.Tensor]
        The inputs loaded from the dataset (images, groundtruth).
    preds : Dict[str, torch.Tensor]
        The model predictions (optical flow and others).
    dataloader_name : str
        A string to identify from which dataloader these inputs came from.
    batch_idx : int
        Indicates in which position of the loader this input is.
    metadata : Dict[str, Any], optional
        Metadata about this input, if available.
    """
    inputs = tensor_dict_to_numpy(inputs)
    inputs["flows_viz"] = flow_utils.flow_to_rgb(inputs["flows"])[:, :, ::-1]
    if inputs.get("flows_b") is not None:
        inputs["flows_b_viz"] = flow_utils.flow_to_rgb(inputs["flows_b"])[:, :, ::-1]
    preds = tensor_dict_to_numpy(preds)
    preds["flows_viz"] = flow_utils.flow_to_rgb(preds["flows"])[:, :, ::-1]
    if preds.get("flows_b") is not None:
        preds["flows_b_viz"] = flow_utils.flow_to_rgb(preds["flows_b"])[:, :, ::-1]

    if args.show:
        _show(inputs, preds, args.max_show_side)

    if args.write_outputs:
        _write_to_file(args, preds, dataloader_name, batch_idx, metadata)


def validate(args: Namespace, model: BaseModel) -> pd.DataFrame:
    """Perform the validation.

    Parameters
    ----------
    args : Namespace
        Arguments to configure the model and the validation.
    model : BaseModel
        The model to be used for validation.

    Returns
    -------
    pd.DataFrame
        A DataFrame with the metric results.

    See Also
    --------
    ptlflow.models.base_model.base_model.BaseModel : The parent class of the available models.
    """
    model.eval()
    if torch.cuda.is_available():
        model = model.cuda()
        if args.fp16:
            model = model.half()

    dataloaders = model.val_dataloader()
    dataloaders = {
        model.val_dataloader_names[i]: dataloaders[i] for i in range(len(dataloaders))
    }

    metrics_df = pd.DataFrame()
    metrics_df["model"] = [args.model]
    metrics_df["checkpoint"] = [args.pretrained_ckpt]

    for dataset_name, dl in dataloaders.items():
        if args.attack == "none":
            metrics_mean = validate_one_dataloader(args, model, dl, dataset_name)
        else: 
            metrics_mean = attack_one_dataloader(args, model, dl, dataset_name)
        metrics_df[[f"{dataset_name}-{k}" for k in metrics_mean.keys()]] = list(
            metrics_mean.values()
        )
        args.output_path.mkdir(parents=True, exist_ok=True)
        metrics_df.T.to_csv(args.output_path / "metrics.csv", header=False)
    metrics_df = metrics_df.round(3)
    return metrics_df


def validate_list_of_models(args: Namespace) -> None:
    """Perform the validation.

    Parameters
    ----------
    args : Namespace
        Arguments to configure the list of models and the validation.
    """
    metrics_df = pd.DataFrame()

    model_names = _get_model_names(args)
    if args.reversed:
        model_names = reversed(model_names)

    exclude = args.exclude
    if exclude is None:
        exclude = []
    for mname in model_names:
        if mname in exclude:
            continue

        logging.info(mname)
        model_ref = ptlflow.get_model_reference(mname)

        if hasattr(model_ref, "pretrained_checkpoints"):
            ckpt_names = model_ref.pretrained_checkpoints.keys()
            for cname in ckpt_names:
                try:
                    logging.info(cname)
                    parser_tmp = model_ref.add_model_specific_args(parser)
                    args = parser_tmp.parse_args()

                    args.model = mname
                    args.pretrained_ckpt = cname

                    model_id = args.model
                    if args.pretrained_ckpt is not None:
                        model_id += f"_{args.pretrained_ckpt}"
                    args.output_path = Path(args.output_path) / model_id

                    model = get_model(mname, cname, args)
                    instance_metrics_df = validate(args, model)
                    metrics_df = pd.concat([metrics_df, instance_metrics_df])
                    args.output_path.parent.mkdir(parents=True, exist_ok=True)
                    if args.reversed:
                        metrics_df.to_csv(
                            args.output_path.parent / "metrics_all_rev.csv", index=False
                        )
                    else:
                        metrics_df.to_csv(
                            args.output_path.parent / "metrics_all.csv", index=False
                        )
                except Exception as e:  # noqa: B902
                    logging.warning("Skipping model %s due to exception %s", mname, e)
                    break


@torch.no_grad()
def validate_one_dataloader(
    args: Namespace,
    model: BaseModel,
    dataloader: DataLoader,
    dataloader_name: str,
) -> Dict[str, float]:
    """Perform validation for all examples of one dataloader.

    Parameters
    ----------
    args : Namespace
        Arguments to configure the model and the validation.
    model : BaseModel
        The model to be used for validation.
    dataloader : DataLoader
        The dataloader for the validation.
    dataloader_name : str
        A string to identify this dataloader.

    Returns
    -------
    Dict[str, float]
        The average metric values for this dataloader.
    """
    metrics_sum = {}

    metrics_individual = None
    if args.write_individual_metrics:
        metrics_individual = {"filename": [], "epe": [], "outlier": []}

    with tqdm(dataloader) as tdl:
        prev_preds = None
        for i, inputs in enumerate(tdl):
            if args.scale_factor is not None:
                scale_factor = args.scale_factor
            else:
                scale_factor = (
                    None
                    if args.max_forward_side is None
                    else float(args.max_forward_side) / min(inputs["images"].shape[-2:])
                )

            io_adapter = IOAdapter(
                model,
                inputs["images"].shape[-2:],
                target_scale_factor=scale_factor,
                cuda=torch.cuda.is_available(),
                fp16=args.fp16,
            )
            inputs = io_adapter.prepare_inputs(inputs=inputs, image_only=True)
            inputs["prev_preds"] = prev_preds

            preds = model(inputs)

            if args.warm_start:
                if (
                    "is_seq_start" in inputs["meta"]
                    and inputs["meta"]["is_seq_start"][0]
                ):
                    prev_preds = None
                else:
                    prev_preds = preds
                    for k, v in prev_preds.items():
                        if isinstance(v, torch.Tensor):
                            prev_preds[k] = v.detach()

            inputs = io_adapter.unscale(inputs, image_only=True)
            preds = io_adapter.unscale(preds)

            if inputs["flows"].shape[1] > 1 and args.seq_val_mode != "all":
                if args.seq_val_mode == "first":
                    k = 0
                elif args.seq_val_mode == "middle":
                    k = inputs["images"].shape[1] // 2
                elif args.seq_val_mode == "last":
                    k = inputs["flows"].shape[1] - 1
                for key, val in inputs.items():
                    if key == "meta":
                        inputs["meta"]["image_paths"] = inputs["meta"]["image_paths"][
                            k : k + 1
                        ]
                    elif key == "images":
                        inputs[key] = val[:, k : k + 2]
                    elif isinstance(val, torch.Tensor) and len(val.shape) == 5:
                        inputs[key] = val[:, k : k + 1]

            metrics = model.val_metrics(preds, inputs)

            for k in metrics.keys():
                if metrics_sum.get(k) is None:
                    metrics_sum[k] = 0.0
                metrics_sum[k] += metrics[k].item()
            tdl.set_postfix(
                epe=metrics_sum["val/epe"] / (i + 1),
                outlier=metrics_sum["val/outlier"] / (i + 1),
            )

            filename = ""
            if "sintel" in inputs["meta"]["dataset_name"][0].lower():
                filename = f'{Path(inputs["meta"]["image_paths"][0][0]).parent.name}/'
            filename += Path(inputs["meta"]["image_paths"][0][0]).stem

            if metrics_individual is not None:
                metrics_individual["filename"].append(filename)
                metrics_individual["epe"].append(metrics["val/epe"].item())
                metrics_individual["outlier"].append(metrics["val/outlier"].item())

            generate_outputs(
                args, inputs, preds, dataloader_name, i, inputs.get("meta")
            )

            if args.max_samples is not None and i >= (args.max_samples - 1):
                break

    if args.write_individual_metrics:
        ind_df = pd.DataFrame(metrics_individual)
        args.output_path.mkdir(parents=True, exist_ok=True)
        ind_df.to_csv(
            Path(args.output_path) / f"{dataloader_name}_epe_outlier.csv", index=None
        )

    metrics_mean = {}
    for k, v in metrics_sum.items():
        metrics_mean[k] = v / len(dataloader)
    return metrics_mean


@torch.enable_grad()
def attack_one_dataloader(
    args: Namespace,
    model: BaseModel,
    dataloader: DataLoader,
    dataloader_name: str,
) -> Dict[str, float]:
    """Perform adversarial attack for all examples of one dataloader.

    Parameters
    ----------
    args : Namespace
        Arguments to configure the model and the validation.
    model : BaseModel
        The model to be used for validation.
    dataloader : DataLoader
        The dataloader for the validation.
    dataloader_name : str
        A string to identify this dataloader.

    Returns
    -------
    Dict[str, float]
        The average metric values for this dataloader.
    """
    metrics_sum = {}

    metrics_individual = None
    if args.write_individual_metrics:
        metrics_individual = {"filename": [], "epe": [], "outlier": []}

    losses = torch.zeros(len(dataloader))
    with tqdm(dataloader) as tdl:
        prev_preds = None
        for i, inputs in enumerate(tdl):
            if args.scale_factor is not None:
                scale_factor = args.scale_factor
            else:
                scale_factor = (
                    None
                    if args.max_forward_side is None
                    else float(args.max_forward_side) / min(inputs["images"].shape[-2:])
                )

            io_adapter = IOAdapter(
                model,
                inputs["images"].shape[-2:],
                target_scale_factor=scale_factor,
                cuda=torch.cuda.is_available(),
                fp16=args.fp16,
            )
            inputs = io_adapter.prepare_inputs(inputs=inputs, image_only=True)
            inputs["prev_preds"] = prev_preds

            # TODO: figure out what to do with scaled images and labels
            match args.attack: # Commit adversarial attack
                case "fgsm":
                    # inputs["images"] = fgsm(args, inputs, model)
                    images, labels, preds, placeholder = fgsm2(args, inputs, model)
                case "ffgsm":
                    # inputs["images"] = fgsm(args, inputs, model)
                    images, labels, preds, placeholder = ffgsm(args, inputs, model)
                case "pgd" | "cospgd":
                    # inputs["images"] = cos_pgd(args, inputs, model)
                    images, labels, preds, losses[i] = cos_pgd(args, inputs, model)
                case "apgd":
                    # inputs["images"] = fgsm(args, inputs, model)
                    images, labels, preds, placeholder = apgd(args, inputs, model)
                case "none":
                    preds = model(inputs)

            if args.warm_start:
                if (
                    "is_seq_start" in inputs["meta"]
                    and inputs["meta"]["is_seq_start"][0]
                ):
                    prev_preds = None
                else:
                    prev_preds = preds
                    for k, v in prev_preds.items():
                        if isinstance(v, torch.Tensor):
                            prev_preds[k] = v.detach()

            inputs = io_adapter.unscale(inputs, image_only=True)
            preds = io_adapter.unscale(preds)

            if inputs["flows"].shape[1] > 1 and args.seq_val_mode != "all":
                if args.seq_val_mode == "first":
                    k = 0
                elif args.seq_val_mode == "middle":
                    k = inputs["images"].shape[1] // 2
                elif args.seq_val_mode == "last":
                    k = inputs["flows"].shape[1] - 1
                for key, val in inputs.items():
                    if key == "meta":
                        inputs["meta"]["image_paths"] = inputs["meta"]["image_paths"][
                            k : k + 1
                        ]
                    elif key == "images":
                        inputs[key] = val[:, k : k + 2]
                    elif isinstance(val, torch.Tensor) and len(val.shape) == 5:
                        inputs[key] = val[:, k : k + 1]

            metrics = model.val_metrics(preds, inputs)

            for k in metrics.keys():
                if metrics_sum.get(k) is None:
                    metrics_sum[k] = 0.0
                metrics_sum[k] += metrics[k].item()
            tdl.set_postfix(
                epe=metrics_sum["val/epe"] / (i + 1),
                outlier=metrics_sum["val/outlier"] / (i + 1),
            )

            filename = ""
            if "sintel" in inputs["meta"]["dataset_name"][0].lower():
                filename = f'{Path(inputs["meta"]["image_paths"][0][0]).parent.name}/'
            filename += Path(inputs["meta"]["image_paths"][0][0]).stem

            if metrics_individual is not None:
                metrics_individual["filename"].append(filename)
                metrics_individual["epe"].append(metrics["val/epe"].item())
                metrics_individual["outlier"].append(metrics["val/outlier"].item())

            generate_outputs(
                args, inputs, preds, dataloader_name, i, inputs.get("meta")
            )

            if args.max_samples is not None and i >= (args.max_samples - 1):
                break

    if args.write_individual_metrics:
        ind_df = pd.DataFrame(metrics_individual)
        args.output_path.mkdir(parents=True, exist_ok=True)
        ind_df.to_csv(
            Path(args.output_path) / f"{dataloader_name}_epe_outlier.csv", index=None
        )

    metrics_mean = {}
    for k, v in metrics_sum.items():
        metrics_mean[k] = v / len(dataloader)
    return metrics_mean


@torch.enable_grad()
def fgsm(args: Namespace,inputs: Dict[str, torch.Tensor], model: BaseModel):
    images = inputs["images"].squeeze(0)
    labels = inputs["flows"].squeeze(0)

    orig_labels = labels.clone()
    orig_images = images.clone()
    images.requires_grad=True
    perturbed_inputs = inputs
    perturbed_inputs["images"] = images.unsqueeze(0)
    preds = model(perturbed_inputs)

    preds_raw = preds["flows"].squeeze(0)

    loss = criterion(preds_raw.float(), labels.float())
    loss = loss.mean()
    loss.backward()
    images = fgsm_attack(args, images, images.grad, orig_images)

    images.requires_grad = True
    perturbed_inputs = inputs
    perturbed_inputs["images"] = images.unsqueeze(0)
    preds = model(perturbed_inputs)

    return images, labels, preds, loss.item()


def fgsm2(args: Namespace, inputs: Dict[str, torch.Tensor], model: BaseModel):
    attack = FGSM(model, args.attack_epsilon)
    perturbed_inputs = attack(inputs)
    preds = model(perturbed_inputs)
    images = None
    labels = None

    return images, labels, preds, None


def ffgsm(args: Namespace, inputs: Dict[str, torch.Tensor], model: BaseModel):
    attack = FFGSM(model, args.attack_epsilon, args.attack_alpha)
    perturbed_inputs = attack(inputs)
    preds = model(perturbed_inputs)
    images = None
    labels = None

    return images, labels, preds, None


def apgd(args: Namespace, inputs: Dict[str, torch.Tensor], model: BaseModel):
    attack = APGD(model, eps=args.attack_epsilon, verbose=True)
    perturbed_inputs = attack(inputs)
    preds = model(perturbed_inputs)
    images = None
    labels = None

    return images, labels, preds, None



@torch.enable_grad()
def cos_pgd(args: Namespace, inputs: Dict[str, torch.Tensor], model: BaseModel):
    """Perform pgd or cospgd adversarial attack on input images.

    Parameters
    ----------
    args : Namespace
        Arguments to configure the model and the validation.
    inputs : Dict[str, torch.Tensor]
        Input images and labels.
    model : BaseModel
        The model for adversarial attack.

    Returns
    -------
    torch.Tensor
        Perturbed images.
    """

    images = inputs["images"].squeeze(0)
    labels = inputs["flows"].squeeze(0)

    orig_labels = labels.clone()
    orig_images = images.clone()
    

    # with torch.no_grad():
    #     orig_preds = model(images)    

    if args.attack_norm == "inf":
        images = attack_functions.init_linf(
                            images,
                            epsilon = args.attack_epsilon,
                            clamp_min = 0,
                            clamp_max = 1
                        )
    elif args.attack_norm == "two":
        images = attack_functions.init_l2(
                            images,
                            epsilon = args.attack_epsilon,
                            clamp_min = 0,
                            clamp_max = 1
                        )
          
    images.requires_grad=True

    perturbed_inputs = inputs
    perturbed_inputs["images"] = images.unsqueeze(0)
    preds = model(perturbed_inputs)
    preds_raw = preds["flows"].squeeze(0)
    
    loss = criterion(preds_raw.float(), labels.float())
    for t in range(args.iterations):
        if args.attack == "cospgd":
            loss = attack_functions.cospgd_scale(
                                predictions = preds_raw,
                                labels = labels.float(),
                                loss = loss,
                                targeted = False,
                                one_hot = False
                            )
        loss = loss.mean()
        loss.backward()
        if args.attack_norm == 'inf':
            images = attack_functions.step_inf(
                perturbed_image = images,
                epsilon = args.attack_epsilon,
                data_grad = images.grad,
                orig_image = orig_images,
                alpha = args.attack_alpha,
                targeted = False,
                clamp_min = 0,
                clamp_max = 1,
                grad_scale = None
            )
        elif args.attack_norm == 'two':
            images = attack_functions.step_l2(
                perturbed_image = images,
                epsilon = args.attack_epsilon,
                data_grad = images.grad,
                orig_image = orig_images,
                alpha = args.attack_alpha,
                targeted = False,
                clamp_min = 0,
                clamp_max = 1,
                grad_scale = None
            )

        images.requires_grad = True
        perturbed_inputs = inputs
        perturbed_inputs["images"] = images.unsqueeze(0)
        preds = model(perturbed_inputs)
        preds_raw = preds["flows"].squeeze(0)
        loss = criterion(preds_raw.float(), labels.float())

    loss = loss.mean()

    return images, labels, preds, loss.item()


def _get_model_names(args: Namespace) -> List[str]:
    if args.model == "all":
        model_names = ptlflow.models_dict.keys()
    elif args.model == "select":
        if args.selection is None:
            raise ValueError(
                "When select is chosen, model names must be provided to --selection."
            )
        model_names = args.selection
    return model_names


def _show(
    inputs: Dict[str, torch.Tensor], preds: Dict[str, torch.Tensor], max_show_side: int
) -> None:
    for k, v in inputs.items():
        if isinstance(v, np.ndarray) and (
            len(v.shape) == 2 or v.shape[2] == 1 or v.shape[2] == 3
        ):
            if max(v.shape[:2]) > max_show_side:
                scale_factor = float(max_show_side) / max(v.shape[:2])
                v = cv.resize(
                    v, (int(scale_factor * v.shape[1]), int(scale_factor * v.shape[0]))
                )
            cv.imshow(k, v)
    for k, v in preds.items():
        if isinstance(v, np.ndarray) and (
            len(v.shape) == 2 or v.shape[2] == 1 or v.shape[2] == 3
        ):
            if max(v.shape[:2]) > max_show_side:
                scale_factor = float(max_show_side) / max(v.shape[:2])
                v = cv.resize(
                    v, (int(scale_factor * v.shape[1]), int(scale_factor * v.shape[0]))
                )
            cv.imshow("pred_" + k, v)
    cv.waitKey(1)


def _write_to_file(
    args: Namespace,
    preds: Dict[str, torch.Tensor],
    dataloader_name: str,
    batch_idx: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    out_root_dir = Path(args.output_path) / dataloader_name

    extra_dirs = ""
    if metadata is not None:
        img_path = Path(metadata["image_paths"][0][0])
        image_name = img_path.stem
        if "sintel" in dataloader_name:
            seq_name = img_path.parts[-2]
            extra_dirs = seq_name
    else:
        image_name = f"{batch_idx:08d}"

    if args.flow_format != "original":
        flow_ext = args.flow_format
    else:
        if "kitti" in dataloader_name or "hd1k" in dataloader_name:
            flow_ext = "png"
        else:
            flow_ext = "flo"

    for k, v in preds.items():
        if isinstance(v, np.ndarray):
            out_dir = out_root_dir / k / extra_dirs
            out_dir.mkdir(parents=True, exist_ok=True)
            if k == "flows" or k == "flows_b":
                flow_utils.flow_write(out_dir / f"{image_name}.{flow_ext}", v)
            elif len(v.shape) == 2 or (
                len(v.shape) == 3 and (v.shape[2] == 1 or v.shape[2] == 3)
            ):
                if v.max() <= 1:
                    v = v * 255
                cv.imwrite(str(out_dir / f"{image_name}.png"), v.astype(np.uint8))


@staticmethod
def fgsm_attack(args: Namespace, perturbed_image, data_grad, orig_image):
    # Collect the element-wise sign of the data gradient
    sign_data_grad = data_grad.sign()
    # Create the perturbed image by adjusting each pixel of the input image        
    if targeted:
        sign_data_grad *= -1
    perturbed_image = perturbed_image.detach() + args.attack_alpha*sign_data_grad
    # Adding clipping to maintain [0,1] range
    if args.attack_norm == 'inf':
        delta = torch.clamp(perturbed_image - orig_image, min = -1*args.attack_epsilon, max=args.attack_epsilon)
    elif args.attack_norm == 'two':
        delta = perturbed_image - orig_image
        delta_norms = torch.norm(delta.view(batch_size, -1), p=2, dim=1)
        factor = args.attack_epsilon / delta_norms
        factor = torch.min(factor, torch.ones_like(delta_norms))
        delta = delta * factor.view(-1, 1, 1, 1)
    perturbed_image = torch.clamp(orig_image + delta, 0, 1)
    # Return the perturbed image
    return perturbed_image


if __name__ == "__main__":
    parser = _init_parser()

    # TODO: It is ugly that the model has to be gotten from the argv rather than the argparser.
    # However, I do not see another way, since the argparser requires the model to load some of the args.
    FlowModel = None
    if len(sys.argv) > 1 and sys.argv[1] not in ["-h", "--help", "all", "select"]:
        FlowModel = get_model_reference(sys.argv[1])
        parser = FlowModel.add_model_specific_args(parser)

    add_datasets_to_parser(parser, "./ptlflow_attacked/datasets.yml")

    args = parser.parse_args()

    if args.model not in ["all", "select"]:
        model_id = args.model
        if args.pretrained_ckpt is not None:
            model_id += f"_{Path(args.pretrained_ckpt).stem}"
        if args.max_forward_side is not None:
            model_id += f"_maxside{args.max_forward_side}"
        if args.scale_factor is not None:
            model_id += f"_scale{args.scale_factor}"
        args.output_path = Path(args.output_path) / model_id
        model = get_model(sys.argv[1], args.pretrained_ckpt, args)
        args.output_path.mkdir(parents=True, exist_ok=True)

        validate(args, model)
    else:
        validate_list_of_models(args)