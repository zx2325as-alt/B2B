import torch
import sys
import os

def check_gpu():
    print(f"Python Version: {sys.version}")
    print(f"PyTorch Version: {torch.__version__}")
    
    cuda_available = torch.cuda.is_available()
    print(f"CUDA Available: {cuda_available}")
    
    if cuda_available:
        print(f"CUDA Version: {torch.version.cuda}")
        print(f"Device Name: {torch.cuda.get_device_name(0)}")
    else:
        print("WARN: Torch is running on CPU. If you have a GPU, please install the CUDA version of PyTorch.")
        print("Example Command: conda install pytorch torchvision torchaudio pytorch-cuda=11.8 -c pytorch -c nvidia")

if __name__ == "__main__":
    try:
        check_gpu()
    except Exception as e:
        print(f"Error checking GPU: {e}")
