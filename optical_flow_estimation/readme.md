# Robustness Benchmark: Adversarial Attacks on Optical Flow Estimation

## Installation
Create Conda environment:
```
conda create --name benchmark python=3.10
conda activate benchmark
```

Install PyTorch version >= 1.13.1 and <= 2.1.2 following the official instructions at https://pytorch.org/.

Install PTLFlow, COSPGD and ImageCorruptions:
```
pip install ptlflow
pip install cospgd
pip install imagecorruptions
```

### Optional Dependencies
Two optional dependencies can be installed to increase the performance of some models.

Install alt_cuda_corr:
```
cd ptlflow_attacked/utils/external/alt_cuda_corr/
python setup.py install
```

Install spatial-correlation-sampler:
```
pip install git+https://github.com/ClementPinard/Pytorch-Correlation-extension.git
```

