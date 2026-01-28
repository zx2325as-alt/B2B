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
    import subprocess
    
    # Check if current ffmpeg works
    ffmpeg_cmd = shutil.which("ffmpeg")
    is_working = False
    
    if ffmpeg_cmd:
        try:
            # Try running ffmpeg -version
            subprocess.run([ffmpeg_cmd, "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logger.info(f"ffmpeg found and working: {ffmpeg_cmd}")
            is_working = True
            return
        except Exception as e:
            logger.warning(f"ffmpeg found at {ffmpeg_cmd} but failed to run: {e}")
            is_working = False

    # Check current environment's Library/bin (Standard Conda)
    env_lib_bin = Path(sys.prefix) / "Library" / "bin"
    ffmpeg_in_env = env_lib_bin / "ffmpeg.exe"
    if ffmpeg_in_env.exists():
        try:
            subprocess.run([str(ffmpeg_in_env), "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logger.info(f"Found working ffmpeg in current env: {ffmpeg_in_env}")
            os.environ["PATH"] = str(env_lib_bin) + os.pathsep + os.environ["PATH"]
            return
        except Exception as e:
            logger.warning(f"ffmpeg in env failed: {e}")

    if not is_working:
        logger.info("Attempting to find alternative ffmpeg in anaconda pkgs...")
        # Search in Anaconda pkgs
        # Common path: C:\Users\...\anaconda3\pkgs\ffmpeg-*\Library\bin
        # We use the user's home directory to be generic, or fallback to known paths
        anaconda_base = Path("C:/Users/19419/anaconda3")
        if not anaconda_base.exists():
             # Try to infer from sys.executable
             # e.g. E:\python\condaEnv\dl-stable\python.exe -> E:\python\condaEnv\dl-stable
             # But pkgs is usually at root of conda install, not env.
             # Try to find 'pkgs' relative to env
             env_path = Path(sys.executable).parent
             # Usually envs are in /envs/name, so up 2 levels is root
             if (env_path.parent.parent / "pkgs").exists():
                 anaconda_base = env_path.parent.parent
             else:
                 # Fallback to standard location
                 anaconda_base = Path("C:/ProgramData/Anaconda3")

        pkgs_dir = anaconda_base / "pkgs"
        if pkgs_dir.exists():
            # Find ffmpeg packages
            ffmpeg_dirs = list(pkgs_dir.glob("ffmpeg-*/Library/bin"))
            if ffmpeg_dirs:
                # Sort by name (version) descending to get latest
                ffmpeg_dirs.sort(key=lambda p: str(p), reverse=True)
                
                # Try each found ffmpeg
                found_working = False
                for f_dir in ffmpeg_dirs:
                    f_path = f_dir / "ffmpeg.exe"
                    if f_path.exists():
                        try:
                            subprocess.run([str(f_path), "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            logger.info(f"Found working ffmpeg in pkgs: {f_path}")
                            # Prepend to PATH
                            os.environ["PATH"] = str(f_dir) + os.pathsep + os.environ["PATH"]
                            found_working = True
                            break
                        except Exception:
                            continue
                
                if not found_working:
                    logger.warning("Found ffmpeg packages but none worked.")
            else:
                logger.warning("Could not find ffmpeg in anaconda pkgs.")

def setup_cuda():
    # Attempt to find CUDA libraries
    # The app requires cublas64_11.dll (CUDA 11) or cublas64_12.dll (CUDA 12).
    
    # Look for system CUDA
    cuda_path_root = Path("C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA")
    if cuda_path_root.exists():
        versions = list(cuda_path_root.glob("v*"))
        versions.sort(reverse=True) # Try latest first
        
        for v in versions:
            bin_dir = v / "bin"
            if bin_dir.exists():
                path_str = str(bin_dir)
                # Add to PATH if not already there
                if path_str not in os.environ["PATH"]:
                    os.environ["PATH"] = path_str + os.pathsep + os.environ["PATH"]
                    logger.info(f"Added CUDA {v.name} bin to PATH: {path_str}")
                
                # Check for key DLLs to verify
                if (bin_dir / "cublas64_11.dll").exists():
                    logger.info(f"Found cublas64_11.dll in {v.name}")
                elif (bin_dir / "cublas64_12.dll").exists():
                    logger.info(f"Found cublas64_12.dll in {v.name}")

    # Also check Conda Library/bin (where cudatoolkit might be)
    # usually in sys.prefix/Library/bin
    conda_lib_bin = Path(sys.prefix) / "Library" / "bin"
    if conda_lib_bin.exists():
         path_str = str(conda_lib_bin)
         if path_str not in os.environ["PATH"]:
             os.environ["PATH"] = path_str + os.pathsep + os.environ["PATH"]
             logger.info(f"Added Conda Library/bin to PATH: {path_str}")
