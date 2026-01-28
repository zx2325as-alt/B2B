import os
import uuid
import yt_dlp
from pathlib import Path
from app.utils.logger import logger

import re

def download_media(url: str, output_dir: str) -> str:
    """
    Download media from URL using yt-dlp.
    Returns path to the downloaded file (wav).
    """
    try:
        # Create output directory if not exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Douyin Modal URL Handling
        # Convert https://www.douyin.com/user/...?modal_id=7572277980479638825 to video URL
        if "douyin.com" in url and "modal_id=" in url:
             match = re.search(r'modal_id=(\d+)', url)
             if match:
                 video_id = match.group(1)
                 url = f"https://www.douyin.com/video/{video_id}"
                 logger.info(f"Converted Douyin Modal URL to: {url}")

        unique_id = str(uuid.uuid4())
        output_template = str(Path(output_dir) / f"{unique_id}.%(ext)s")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # The file should be at output_dir / {unique_id}.wav
        expected_path = Path(output_dir) / f"{unique_id}.wav"
        
        if expected_path.exists():
            logger.info(f"Downloaded media: {expected_path}")
            return str(expected_path)
        else:
            logger.error(f"Downloaded file not found at expected path: {expected_path}")
            return None

    except Exception as e:
        logger.error(f"Download failed: {e}")
        return None
