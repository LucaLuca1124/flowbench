from argparse import  Namespace
from typing import Any, Dict, List, Optional
import torch
from ptlflow_attacked.ptlflow.models.base_model.base_model import BaseModel
from attacks.attack_utils.utils import get_image_tensors, get_image_grads, replace_images_dic, get_flow_tensors
import torch.nn as nn
import attacks.attack_utils.loss_criterion as losses


# PCFA parameters
import torch.optim as optim
delta_bound=0.005


def pcfa(args: Namespace, inputs: Dict[str, torch.Tensor], model: BaseModel, targeted_inputs: Optional[Dict[str, torch.Tensor]]):
    """
    Performs an PCFA attack on a given model and for all images of a specified dataset.
    """

    optim_mu = 2500./args.pcfa_delta_bound
        
    optimizer_lr = args.pcfa_delta_bound

    eps_box = 1e-7

    # Define what device we are using
    if not torch.cuda.is_available():
        device = torch.device("cpu")
    else:
        device = torch.device("cuda")

    # Make sure the model is not trained:
    # for param in model.parameters():
    #     param.requires_grad = False
    
    # If dataset has ground truth
    has_gt = True

    # if args.attack_targeted:
    #     labels = targeted_inputs["flows"].squeeze(0)
    # else:
    

    orig_image_1 = inputs["images"][0].clone()[0].unsqueeze(0)
    orig_image_2 = inputs["images"][0].clone()[1].unsqueeze(0)

    aee_gt, aee_tgt, aee_gt_tgt, aee_adv_gt, aee_adv_tgt, aee_adv_pred, l2_delta1, l2_delta2, l2_delta12, aee_adv_tgt_min_val, aee_adv_pred_min_val, delta12_min_val = pcfa_attack(model, inputs, targeted_inputs, eps_box, device, optimizer_lr, has_gt, optim_mu, args)
    

def pcfa_attack(model, inputs, targeted_inputs, flow, eps_box, device, optimizer_lr, has_gt, optim_mu, args):
    """Subroutine to optimize a PCFA perturbation on a given image pair. For a specified number of steps.

    Args:
        model (torch.nn.module):
            a pytorch model which is set to eval and which is implemented in ownutilities.['preprocess_img','compute_flow','postprocess_flow']
        image1 (torch.tensor):
            image 1 of a scene with dimensions (b,3,h,w)
        image2 (torch.tensor):
            image 2 of a scene with dimensions (b,3,h,w)
        flow (torch.tensor):
            intial (unattacked) flow field (resulting from img1 and img2) which can be used to log the current effect induced by the patch (same spatial dimension as images!)
        batch (int):
            current image counter in the enumeration of the test set
        distortion_folder (string):
            name for a folder that will be created to hold data and visualizations of the distortions that are trained during the PCFA
        eps_box (float):
            relaxation of the box constraint due to numerical reasons (try 1e-07)
        device (torch.device):
            Select the device for the images.
        optimizer_lr (float):
            optimizer learning rate (try 5e-03)
        has_gt (boolean):
            is the ground truth known
        optim_mu (float):
            regularization parameter of the constraint in the unconstraing optimization (try 5e05)
        args (Namespace):
            command line arguments


    Returns:
        aee_gt (float):
            Average Endpoint Error of the ground truth w.r.t. zero flow (none if has_gt is false)
        aee_tgt (float):
            Average Endpoint Error of the target flow w.r.t. zero flow
        aee_gt_tgt (float):
            Average Endpoint Error of the ground truth towards the target flow (none if has_gt is false)
        aee_adv_tgt (float):
            Average Endpoint Error of the adversarial predicted flow (after the perturbation is added) towards the target flow
        aee_adv_pred (float):
            Average Endpoint Error of the adversarial predicted flow (after the perturbation is added) towards the initially predicted flow
        l2_delta2 (float):
            l2 error of the preturbation on image1
        l2_delta2 (float):
            l2 error of the preturbation on image2
        l2_delta12 (float):
            scalar average L2-norm of two perturbations
        aee_adv_tgt_min_val (float):
            minimal (best attack) Average Endpoint Error of the adversarial predicted flow towards the target flow, while also not violating the constraint, i.e. delta12 < args.delta_bound
        aee_adv_pred_min_val (float):
            best attack Average Endpoint Error of the adversarial predicted flow towards the initially predicted flow, while also not violating the constraint
        delta12_min_val (float):
            scalar average L2-norm of two perturbations of the best attack

    Extended Output:
        Files in .npy and .png format of initial images and flow, perturbations, and the adversarial images and flow are saved.
        The best attack perturbation images and flows are labeled with "*best*" and correspond to the values of "*_min*".
    """
    torch.autograd.set_detect_anomaly(True)

    image1, image2 = get_image_tensors(targeted_inputs)
    image1, image2 = image1.to(device), image2.to(device)

    flow = get_flow_tensors(targeted_inputs)
    flow = flow.to(device)

    # Set requires_grad attribute of tensor. Important for Attack
    image1.requires_grad = False
    image2.requires_grad = False

    # initialize perturbation and auxiliary variables:
    delta1 = torch.zeros_like(image1)
    delta2 = torch.zeros_like(image2)
    delta1 = delta1.to(device)
    delta2 = delta2.to(device)

    nw_input1 = None
    nw_input2 = None

    flow_pred_init = None

    # Set up the optimizer and variables if individual perturbations delta1 and delta2 for images 1 and 2 should be trained
    delta1.requires_grad = False
    delta2.requires_grad = False

    if args.pcfa_boxconstraint in ['change_of_variables']:
        nw_input1 = torch.atanh( 2. * (1.- eps_box) * (image1 + delta1) - (1 - eps_box)  )
        nw_input2 = torch.atanh( 2. * (1.- eps_box) * (image2 + delta2) - (1 - eps_box)  )
    else:
        nw_input1 = image1 + delta1
        nw_input2 = image2 + delta2

    nw_input1.requires_grad = True
    nw_input2.requires_grad = True

    optimizer = optim.LBFGS([nw_input1, nw_input2], max_iter=10)

    # Predict the flow
    perturbed_inputs = replace_images_dic(targeted_inputs, nw_input1, nw_input2)
    perturbed_inputs["images"].requires_grad_(True)
    flow_pred = model(perturbed_inputs)
    # TDO: maybe have to add brackets? [flow_pred] = ownutilities.postprocess_flow(args.net, padder, flow_pred)
    flow_pred = flow_pred.to(device)

    # define the initial flow, the target, and update mu
    flow_pred_init = flow_pred.detach().clone()
    flow_pred_init.requires_grad = False


    # define target (potentially based on first flow prediction)
    # define attack target
    target = get_flow_tensors(targeted_inputs)
    target = target.to(device)
    target.requires_grad = False

    # Zero all existing gradients
    model.zero_grad()
    optimizer.zero_grad()

    

    for steps in range(args.pcfa_steps):

        curr_step = steps

        # Calculate the deltas from the quantities that go into the network
        delta1, delta2 = extract_deltas(nw_input1, nw_input2, image1, image2, args.boxconstraint, eps_box=eps_box)

        # Calculate the loss
        # if args.delta_bound > 0.0:
        loss = losses.loss_delta_constraint(flow_pred, target, delta1, delta2, device, delta_bound=args.delta_bound, mu=optim_mu,  f_type="aee")

        # else:
        #     # print('using loss weighted')
        #     loss = losses.loss_weighted(flow_pred, target, delta1, delta2, c=args.weighting, f_type="aee")


        # Update the optimization parameters
        loss.backward()

        def closure():
            optimizer.zero_grad()
            flow_closure = model(perturbed_inputs)
            
            # TODO: maybe have to add rbackets? [flow_closure] = ownutilities.postprocess_flow(args.net, padder, flow_closure)
            flow_closure = flow_closure.to(device)
            delta1_closure, delta2_closure = extract_deltas(nw_input1, nw_input2, image1, image2, args.boxconstraint, eps_box=eps_box)
            loss_closure = losses.loss_delta_constraint(flow_closure, target, delta1_closure, delta2_closure, device, delta_bound=args.delta_bound, mu=optim_mu,  f_type=args.loss)
            loss_closure.backward()

            return loss_closure

        # Update the optimization parameters
        optimizer.step(closure)

        # calculate the magnitude of the updated distortion, and with it the new network inputs:
        delta1, delta2 = extract_deltas(nw_input1, nw_input2, image1, image2, args.pcfa_boxconstraint, eps_box=eps_box)
        # The nw_inputs remain unchanged in this case, and can be directly fed into the network again for further perturbation training

        # Re-predict flow with the perturbed image, and update the flow prediction for the next iteration
        perturbed_inputs = replace_images_dic(perturbed_inputs, nw_input1, nw_input2)
        perturbed_inputs["images"].requires_grad_(True)
        flow_pred = model(perturbed_inputs)
        # [flow_pred] = ownutilities.postprocess_flow(args.net, padder, flow_pred)
        flow_pred = flow_pred.to(device)

    return flow_pred


# For PCFA
def extract_deltas(nw_input1, nw_input2, image1, image2, boxconstraint, eps_box=0.):

    if boxconstraint in ['change_of_variables']:
        delta1 = (1./2.)*1./(1.-eps_box)*(torch.tanh(nw_input1) + (1.-eps_box)) - image1
        delta2 = (1./2.)*1./(1.-eps_box)*(torch.tanh(nw_input2) + (1.-eps_box)) - image2
    else: # case clipping (ScaledInputModel also treats everything that is not change_of_variables by clipping it into range before feeding it to network.)
        delta1 = torch.clamp(nw_input1, 0., 1.) - image1
        delta2 = torch.clamp(nw_input2, 0., 1.) - image2

    return delta1, delta2