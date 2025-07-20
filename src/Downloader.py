import os
import sys
import time
import logging
import shutil
import subprocess
import csv
from pathlib import Path

from dotenv import load_dotenv
import yt_dlp

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

HERE           = Path(__file__).resolve().parent
PROJECT_ROOT   = HERE.parent

TARGET_USERNAME = os.getenv("TARGET_USERNAME", "aa19aa199")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
VIDEOS_DIR = os.getenv("VIDEOS_DIR", "videos")

DEFAULT_OUTPUT = PROJECT_ROOT / VIDEOS_DIR
COOKIES_FILE   = HERE / "twitter_cookies.txt"

def find_latest_csv():
    output_path = PROJECT_ROOT / OUTPUT_DIR
    if not output_path.exists():
        return None
    
    pattern = f"{TARGET_USERNAME}_media_posts_full_*.csv"
    csv_files = list(output_path.glob(pattern))
    
    if not csv_files:
        return None
    
    return max(csv_files, key=lambda x: x.stat().st_mtime)

DEFAULT_CSV = find_latest_csv()

TW_USER = os.getenv("TWITTER_USERNAME")
TW_PASS = os.getenv("TWITTER_PASSWORD")

def download_stream(url: str, template: str, fmt: str):
    opts = {
        "format": fmt,
        "outtmpl": template,
        "cookiefile": str(COOKIES_FILE),
        "quiet": False,
        "retries": 10,
        "fragment_retries": 10,
    }
    if TW_USER and TW_PASS:
        opts["username"] = TW_USER
        opts["password"] = TW_PASS
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

def merge_with_ffmpeg(video_file: Path, audio_file: Path, output_file: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logging.error("ffmpeg not found in PATH. Install ffmpeg to merge streams.")
        return False

    cmd = [
        ffmpeg,
        "-i", str(video_file),
        "-i", str(audio_file),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        "-y",
        str(output_file)
    ]
    logging.info(f"Merging streams into {output_file.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error(f"ffmpeg merge failed: {result.stderr.strip()}")
        return False

    try:
        video_file.unlink()
        audio_file.unlink()
    except Exception:
        pass
    return True

def download_tweet_video(url: str, output_root: Path, user: str, post_id: str):
    user_dir = output_root / user
    user_dir.mkdir(parents=True, exist_ok=True)

    final_mp4 = user_dir / f"{post_id}.mp4"
    video_tpl = str(user_dir / f"{post_id}.video.%(ext)s")
    audio_tpl = str(user_dir / f"{post_id}.audio.%(ext)s")

    logging.info(f"[{user}] Downloading video stream: {url}")
    download_stream(url, video_tpl, "bestvideo[height<=720]")

    logging.info(f"[{user}] Downloading audio stream: {url}")
    download_stream(url, audio_tpl, "bestaudio/best")

    video_files = list(user_dir.glob(f"{post_id}.video.*"))
    audio_files = list(user_dir.glob(f"{post_id}.audio.*"))
    if not video_files or not audio_files:
        logging.error(f"Streams missing for {post_id}. video: {video_files}, audio: {audio_files}")
        return

    success = merge_with_ffmpeg(video_files[0], audio_files[0], final_mp4)
    if success:
        logging.info(f"[{user}] Merged into {final_mp4.name}")
    else:
        logging.error(f"[{user}] Merge failed for {post_id}")

def main():
    csv_path    = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    output_root = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT

    if csv_path is None:
        logging.error(f"No CSV file found for user '{TARGET_USERNAME}'. Please run getId.py first or provide CSV path as argument.")
        print(f"Expected CSV pattern: {TARGET_USERNAME}_media_posts_full_*.csv in {PROJECT_ROOT / OUTPUT_DIR}")
        sys.exit(1)

    logging.info(f"CSV file: {csv_path}")
    logging.info(f"Output directory: {output_root}")
    logging.info(f"Target username: {TARGET_USERNAME}")

    if not csv_path.is_file():
        logging.error(f"CSV file not found: {csv_path}")
        sys.exit(1)

    output_root.mkdir(parents=True, exist_ok=True)

    existing_files = set()
    for user_dir in output_root.iterdir():
        if user_dir.is_dir():
            for file in user_dir.glob("*.mp4"):
                existing_files.add(file.stem)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("media_type") != "video":
                continue

            post_id = row.get("post_id", "").strip()
            user    = row.get("username", "unknown").strip()

            if post_id in existing_files:
                logging.info(f"[{user}] {post_id}.mp4 already exists, skipping")
                continue

            tweet_url = row.get("full_url") or row.get("original_href")
            if not tweet_url:
                logging.warning(f"Missing URL in row: {row}")
                continue
            if tweet_url.startswith("/"):
                tweet_url = "https://x.com" + tweet_url

            logging.info(f"[{user}] Processing {tweet_url}")
            try:
                download_tweet_video(tweet_url, output_root, user, post_id)
                existing_files.add(post_id)
                time.sleep(1)
            except Exception as e:
                logging.error(f"Failed {tweet_url}: {e}")

    logging.info("All downloads complete.")

if __name__ == "__main__":
    main()