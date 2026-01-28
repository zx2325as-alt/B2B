import os
import subprocess
import sys

# 系统ffmpeg路径（根据实际情况修改）
system_ffmpeg_path = r"C:\ffmpeg\bin"

# 将系统ffmpeg路径添加到环境变量PATH中
os.environ['PATH'] = system_ffmpeg_path + ';' + os.environ['PATH']

# 测试ffmpeg
try:
    result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, shell=True)
    if result.returncode == 0:
        print("✓ System ffmpeg found and working")
    else:
        print("✗ System ffmpeg not working")
except Exception as e:
    print(f"✗ Error: {e}")

# 然后导入pyannote.audio等