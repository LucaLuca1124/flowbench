#!/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=100G
#SBATCH --time=01:29:59
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:1
#SBATCH --partition=gpu_4
#SBATCH --array=0-14%4
#SBATCH --job-name=separableflow_sintel-clean_cc
#SBATCH --output=slurm/separableflow_sintel-clean_cc_%A_%a.out
#SBATCH --error=slurm/separableflow_sintel-clean_cc_err_%A_%a.out

model="separableflow"
dataset="sintel-clean"
checkpoint="sintel"
attack="common_corruptions"
cc_names="gaussian_noise shot_noise impulse_noise defocus_blur glass_blur motion_blur zoom_blur snow frost fog brightness contrast elastic_transform pixelate jpeg_compression"
cc_severitys="3"
jobnum=0

#SLURM_ARRAY_TASK_ID=0

cd ../../../../
for cc_name in $cc_names
do
    for cc_severity in $cc_severitys
    do
        if [[ $SLURM_ARRAY_TASK_ID -eq $jobnum ]]
        then
            echo "Running job $model $checkpoint $dataset $attack $cc_name $cc_severity $jobnum"
            python attacks.py \
                $model \
                --pretrained_ckpt $checkpoint \
                --val_dataset $dataset \
                --attack $attack \
                --cc_name $cc_name \
                --cc_severity $cc_severity \
                --write_outputs                                       
            #SLURM_ARRAY_TASK_ID=$((SLURM_ARRAY_TASK_ID + 1))
        fi
        jobnum=$((jobnum + 1))
    done
done