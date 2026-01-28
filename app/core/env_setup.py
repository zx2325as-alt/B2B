import os
import sys
import glob
from pathlib import Path
from app.utils.logger import logger

def setup_environment():
    """
    Setup environment variables and paths before application startup.
    This attempts to fix missing DLL/EXE issues by finding them in common locations.
    """
    logger.info("Running environment setup...")
    
    # 1. Setup FFmpeg
    setup_ffmpeg()
    
    # 2. Setup CUDA
    setup_cuda()
    
    # 3. Fix Intel MKL / libifcoremd.dll issues
    # "OMP: Error #15: Initializing libiomp5md.dll, but found libiomp5md.dll already initialized."
    # or general DLL conflicts with numpy/torch
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    logger.info("Set KMP_DUPLICATE_LIB_OK=TRUE to prevent MKL conflicts.")

def setup_ffmpeg():
    import shutil
    if shutil.which("ffmpeg"):
        logger.info("ffmpeg found in PATH.")
        return

    # Search in Anaconda pkgs
    # Common path: C:\Users\...\anaconda3\pkgs\ffmpeg-*\Library\bin
    # We use the user's home directory to be generic, or fallback to known paths
    anaconda_base = Path("C:/Users/19419/anaconda3")
    if not anaconda_base.exists():
         # Try to infer from sys.executable
         anaconda_base = Path(sys.executable).parent
    
    pkgs_dir = anaconda_base / "pkgs"
    if pkgs_dir.exists():
        # Find ffmpeg packages
        ffmpeg_dirs = list(pkgs_dir.glob("ffmpeg-*/Library/bin"))
        if ffmpeg_dirs:
            # Sort by name (version) descending to get latest
            ffmpeg_dirs.sort(key=lambda p: str(p), reverse=True)
            ffmpeg_path = str(ffmpeg_dirs[0])
            
            # Add to PATH
            os.environ["PATH"] = ffmpeg_path + os.pathsep + os.environ["PATH"]
            logger.info(f"Added FFmpeg to PATH: {ffmpeg_path}")
        else:
            logger.warning("Could not find ffmpeg in anaconda pkgs.")

def setup_cuda():
    # Attempt to find CUDA libraries
    # The app requires cublas64_12.dll (CUDA 12).
    # If not found, we try to add CUDA 11 path just in case, or look for CUDA 12.
    
    # Check if we have CUDA 12 libs in known locations
    # (e.g. nvidia-cublas-cu12 in site-packages)
    # This is handled by python imports usually, but sometimes PATH is needed.
    
    # Look for system CUDA
    cuda_path_root = Path("C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA")
    if cuda_path_root.exists():
        versions = list(cuda_path_root.glob("v*"))
        versions.sort(reverse=True) # Try latest first
        
        for v in versions:
            bin_dir = v / "bin"
            if bin_dir.exists():
                path_str = str(bin_dir)
                if path_str not in os.environ["PATH"]:
                    os.environ["PATH"] = path_str + os.pathsep + os.environ["PATH"]
                    logger.info(f"Added CUDA {v.name} bin to PATH: {path_str}")
                
                # Also check for cudnn
                # sometimes it is in a different dir, but usually if installed via installer it's in bin or separate
