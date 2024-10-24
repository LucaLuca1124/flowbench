#!/bin/bash
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --mem=100G
#SBATCH --time=00:59:00
#SBATCH --job-name=3DCClowlight_kitti2015_test
#SBATCH --output=slurm/3DCClowlight_kitti2015_test.out
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:1
#SBATCH --partition=gpu_4
#SBATCH --error=slurm/3DCClowlight_kitti2015_test.out

rgb_path=/pfs/work7/workspace/scratch/ma_jcaspary-team_project_fss2024/datasets/kitti2015/testing/image_2
depth_path=/pfs/work7/workspace/scratch/ma_jcaspary-team_project_fss2024/datasets_depth/kitti2015/testing/image_2
output_path=/pfs/work7/workspace/scratch/ma_jcaspary-team_project_fss2024/datasets_corrupted/kitti2015/testing/image_2
cd /pfs/work7/workspace/scratch/ma_jcaspary-team_project_fss2024/3DCommonCorruptions/create_3dcc
# python create_3dcc.py --path_rgb /pfs/work7/workspace/scratch/ma_jcaspary-team_project_fss2024/datasets/kitti2015/training/image_2 --path_depth /pfs/work7/workspace/scratch/ma_jcaspary-team_project_fss2024/datasets_depth/kitti2015/training/image_2 --path_target /pfs/work7/workspace/scratch/ma_jcaspary-team_project_fss2024/datasets_corrupted/kitti2015/training/image_2 --batch_size 1
python create_3dcc_low_light.py --path_rgb $rgb_path --path_depth $depth_path --path_target $output_path --batch_size 1

#python create_3dcc.py --path_rgb /pfs/work7/workspace/scratch/ma_jcaspary-team_project_fss2024/test/rgb --path_depth /pfs/work7/workspace/scratch/ma_jcaspary-team_project_fss2024/test/depth --path_target /pfs/work7/workspace/scratch/ma_jcaspary-team_project_fss2024/test --batch_size 1
