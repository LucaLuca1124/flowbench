#!/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=100G
#SBATCH --time=00:44:59
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:1
#SBATCH --partition=gpu_4
#SBATCH --array=0-3%4
#SBATCH --job-name=irr_pwc_sintel-final_fgsm_inf
#SBATCH --output=slurm/irr_pwc_sintel-final_fgsm_inf_%A_%a.out
#SBATCH --error=slurm/irr_pwc_sintel-final_fgsm_inf_err_%A_%a.out

model="irr_pwc"
dataset="sintel-final"
checkpoint="sintel"
targeteds="True False"
targets="negative zero"
norm="inf"
attacks="fgsm"
jobnum=0
#SLURM_ARRAY_TASK_ID=0

cd ../../../../


for targeted in $targeteds
do
    if [[ $targeted = "False" ]]
    then
        epsilons="4 8"
        alphas="0.01"          
    elif [[ $targeted = "True" ]]
    then
        epsilons="8"
        alphas="0.01"
    fi
    for epsilon in $epsilons
    do
        epsilon=$(echo "scale=10; $epsilon/255" | bc)
        for alpha in $alphas
        do
            for attack in $attacks
            do

                if [[ $targeted = "True" ]]
                then
                    for target in $targets
                    do      
                        if [[ $SLURM_ARRAY_TASK_ID -eq $jobnum ]]
                        then
                            echo "Running job $model $checkpoint $dataset $attack $iteration $norm $alpha $epsilon $targeted $target $jobnum"
                            python attacks.py \
                                $model \
                                --pretrained_ckpt $checkpoint \
                                --val_dataset $dataset \
                                --attack $attack \
                                --attack_norm $norm \
                                --attack_alpha $alpha \
                                --attack_epsilon $epsilon \
                                --attack_targeted $targeted \
                                --attack_target $target \
                                --write_outputs                                       
                            #SLURM_ARRAY_TASK_ID=$((SLURM_ARRAY_TASK_ID + 1))
                        fi
                        jobnum=$((jobnum + 1))
                    done
                else                           
                    if [[ $SLURM_ARRAY_TASK_ID -eq $jobnum ]]
                    then
                        echo "Running job $model $checkpoint $dataset $attack $iteration $norm $alpha $epsilon $targeted $target $jobnum"
                        python attacks.py \
                            $model \
                            --pretrained_ckpt $checkpoint \
                            --val_dataset $dataset \
                            --attack $attack \
                            --attack_norm $norm \
                            --attack_alpha $alpha \
                            --attack_epsilon $epsilon \
                            --attack_targeted $targeted \
                            --attack_target "zero" \
                            --write_outputs 
                        #SLURM_ARRAY_TASK_ID=$((SLURM_ARRAY_TASK_ID + 1))
                    fi
                    jobnum=$((jobnum + 1))
                fi
            done
        done
    done
done
