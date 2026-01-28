import os
import subprocess
import concurrent.futures
import sys
import shutil
from pathlib import Path
try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

def get_ffmpeg_path():
    """
    获取ffmpeg可执行文件的路径
    """
    # 0. 优先使用imageio_ffmpeg
    if imageio_ffmpeg:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass

    # 1. 检查系统环境变量
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return ffmpeg_path
        
    # 2. 检查当前Conda环境 (Windows)
    if sys.platform == 'win32':
        conda_prefix = sys.prefix
        possible_path = Path(conda_prefix) / "Library" / "bin" / "ffmpeg.exe"
        if possible_path.exists():
            return str(possible_path)
            
    return 'ffmpeg'

def extract_audio_ffmpeg(video_path, output_dir, audio_format="mp3"):
    """
    使用ffmpeg提取视频中的音频
    """
    try:
        ffmpeg_cmd = get_ffmpeg_path()
        
        # 构建输出文件路径
        video_name = Path(video_path).stem
        output_path = Path(output_dir) / f"{video_name}.{audio_format}"
        
        # 根据音频格式选择编码器
        if audio_format == "mp3":
            codec = "libmp3lame"
            bitrate = "192k"
            cmd = [
                ffmpeg_cmd, '-i', str(video_path),
                '-vn',  # 不处理视频
                '-acodec', codec,
                '-ab', bitrate,
                '-y',  # 覆盖已存在的文件
                str(output_path)
            ]
        elif audio_format == "wav":
            cmd = [
                ffmpeg_cmd, '-i', str(video_path),
                '-vn',
                '-acodec', 'pcm_s16le',
                '-ar', '44100',
                '-ac', '2',
                '-y',
                str(output_path)
            ]
        elif audio_format == "aac":
            cmd = [
                ffmpeg_cmd, '-i', str(video_path),
                '-vn',
                '-acodec', 'aac',
                '-strict', 'experimental',
                '-b:a', '192k',
                '-y',
                str(output_path)
            ]
        else:
            cmd = [
                ffmpeg_cmd, '-i', str(video_path),
                '-vn',
                '-acodec', 'copy',  # 保持原始音频编码
                '-y',
                str(output_path)
            ]
        
        # 执行命令
        # print(f"Executing: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            return True, video_path, output_path
        else:
            return False, video_path, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            
    except Exception as e:
        return False, video_path, str(e)

def batch_extract_audio(input_dir, output_dir, audio_format="mp3", max_workers=None):
    """
    批量提取音频（并行处理）
    """
    # 支持的视频格式
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.m4v', '.mpg', '.mpeg'}
    
    # 创建输出目录
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 收集所有视频文件
    video_files = []
    for ext in video_extensions:
        video_files.extend(Path(input_dir).glob(f'*{ext}'))
        video_files.extend(Path(input_dir).glob(f'*{ext.upper()}'))
    
    if not video_files:
        print(f"在目录 {input_dir} 中未找到视频文件")
        return
    
    print(f"找到 {len(video_files)} 个视频文件")
    
    # 使用线程池并行处理
    successful = 0
    failed = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_file = {
            executor.submit(extract_audio_ffmpeg, str(video), output_dir, audio_format): video
            for video in video_files
        }
        
        # 处理结果
        for future in concurrent.futures.as_completed(future_to_file):
            video_file = future_to_file[future]
            try:
                success, file_path, result = future.result()
                if success:
                    print(f"✓ 成功提取: {Path(file_path).name} -> {Path(result).name}")
                    successful += 1
                else:
                    print(f"✗ 失败: {Path(file_path).name} - {result}")
                    failed += 1
            except Exception as e:
                print(f"✗ 异常: {video_file.name} - {str(e)}")
                failed += 1
    
    print(f"\n处理完成: 成功 {successful} 个，失败 {failed} 个")
    print(f"音频文件保存在: {output_dir}")

# 使用方法
if __name__ == "__main__":
    # 配置参数
    INPUT_DIR = r"C:\Users\19419\Videos"      # 视频目录
    OUTPUT_DIR = r"C:\Users\19419\Audio"      # 输出目录
    AUDIO_FORMAT = "wav"                    # 音频格式：mp3, wav, aac等
    MAX_WORKERS = 4                         # 并行处理数（根据CPU核心数调整）
    
    # 执行批量提取
    batch_extract_audio(INPUT_DIR, OUTPUT_DIR, AUDIO_FORMAT, MAX_WORKERS)
