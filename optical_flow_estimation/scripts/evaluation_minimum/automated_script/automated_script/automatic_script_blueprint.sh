#!/bin/bash
#SBATCH --ntasks=1
#SBATCH --mem=100G
#SBATCH --time=19:59:59
#SBATCH --gres=gpu:4
#SBATCH --partition=accelerated
#SBATCH --job-name=automatic_script
#SBATCH --output=slurm/automatic_script_%A_%a.out
#SBATCH --error=slurm/automatic_script_err_%A_%a.out
#SBATCH --array=0-19%4

# Combinations array is dynamically generated by the Python script

# Echo the content of the combinations array
echo "Generated combinations:"
for comb in "${combinations[@]}"; do
    echo "$comb"
done

# Calculate the number of SLURM array tasks
total_jobs=${#combinations[@]}
echo "Total number of jobs: $total_jobs"
jobs_per_task=4  # Number of jobs to run per SLURM task

# Compute the total number of array tasks (rounding up)
array_length=$(( (total_jobs + jobs_per_task - 1) / jobs_per_task ))

# If running as part of a SLURM array job, determine start job
if [ -z "$SLURM_ARRAY_TASK_ID" ]; then
    SLURM_ARRAY_TASK_ID=0
fi

start_job=$(( SLURM_ARRAY_TASK_ID * jobs_per_task ))

# Run up to 4 combinations on separate GPUs
for i in $(seq 0 3)  # Loop over 4 GPUs (0 to 3)
do
    jobnum=$(( start_job + i ))
    
    if [[ $jobnum -lt $total_jobs ]]
    then
        # Get the combination for the current task
        combination="${combinations[$jobnum]}"
        
        # Extract the individual variables from the combination string
        IFS=' ' read -r model pretrained_ckpt val_dataset attack attack_targeted attack_target attack_loss attack_epsilon attack_alpha attack_iterations attack_norm cc_name cc_severity attack_optim_target <<< "$combination"
        
        # Set the GPU for this job
        export CUDA_VISIBLE_DEVICES=$i

        # Construct the Python command dynamically, excluding 'nan' values
        python_command="python attacks.py $model --pretrained_ckpt $pretrained_ckpt --val_dataset $val_dataset --attack $attack"

        # Only add the optional arguments if they are non-empty and not 'nan'
        [[ -n "$attack_targeted" && "$attack_targeted" != "nan" ]] && python_command+=" --attack_targeted $attack_targeted"
        [[ -n "$attack_target" && "$attack_target" != "nan" ]] && python_command+=" --attack_target $attack_target"
        [[ -n "$attack_loss" && "$attack_loss" != "nan" ]] && python_command+=" --attack_loss $attack_loss"
        [[ -n "$attack_epsilon" && "$attack_epsilon" != "nan" ]] && python_command+=" --attack_epsilon $attack_epsilon"
        [[ -n "$attack_alpha" && "$attack_alpha" != "nan" ]] && python_command+=" --attack_alpha $attack_alpha"
        [[ -n "$attack_iterations" && "$attack_iterations" != "nan" ]] && python_command+=" --attack_iterations $attack_iterations"
        [[ -n "$attack_norm" && "$attack_norm" != "nan" ]] && python_command+=" --attack_norm $attack_norm"
        [[ -n "$cc_name" && "$cc_name" != "nan" ]] && python_command+=" --cc_name $cc_name"
        [[ -n "$cc_severity" && "$cc_severity" != "nan" ]] && python_command+=" --cc_severity $cc_severity"
        [[ -n "$attack_optim_target" && "$attack_optim_target" != "nan" ]] && python_command+=" --attack_optim_target $attack_optim_target"

        # Ensure --write_outputs is always at the end
        python_command+=" --write_outputs"

        # Run the dynamically constructed Python command in the background (&)
        echo "Executing: $python_command"
        eval $python_command &
    fi
done

# Wait for all background jobs to complete before exiting
wait
