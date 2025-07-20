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
from yt_dlp.utils import DownloadError

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

HERE            = Path(__file__).resolve().parent
PROJECT_ROOT    = HERE.parent
TARGET_USERNAME = os.getenv("TARGET_USERNAME", "aa19aa199")
OUTPUT_DIR      = os.getenv("OUTPUT_DIR", "output")
VIDEOS_DIR      = os.getenv("VIDEOS_DIR", "videos")

def find_latest_csv():
    output_path = PROJECT_ROOT / OUTPUT_DIR
    if not output_path.exists():
        return None
    pattern = f"{TARGET_USERNAME}_media_posts_full_*.csv"
    csv_files = list(output_path.glob(pattern))
    return max(csv_files, key=lambda x: x.stat().st_mtime) if csv_files else None

DEFAULT_CSV    = find_latest_csv()
DEFAULT_OUTPUT = PROJECT_ROOT / VIDEOS_DIR
COOKIES_FILE   = HERE / "x.com_cookies.txt"

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
        opts.update({"username": TW_USER, "password": TW_PASS})
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

def merge_with_ffmpeg(video_file: Path, audio_file: Path, output_file: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logging.error("ffmpeg not found in PATH. Install ffmpeg to merge streams.")
        return False
    cmd = [
        ffmpeg, "-i", str(video_file), "-i", str(audio_file),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "copy",
        "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart",
        "-y", str(output_file)
    ]
    logging.info(f"Merging streams into {output_file.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error(f"ffmpeg merge failed: {result.stderr.strip()}")
        return False
    for f in (video_file, audio_file):
        try: f.unlink()
        except: pass
    return True

def download_tweet_video(url: str, output_root: Path, user: str, post_id: str) -> bool:
    user_dir = output_root / user
    user_dir.mkdir(parents=True, exist_ok=True)
    final_mp4 = user_dir / f"{post_id}.mp4"
    if final_mp4.exists():
        logging.info(f"[{user}] {post_id}.mp4 already exists, skipping")
        return True

    video_tpl    = str(user_dir / f"{post_id}.video.%(ext)s")
    audio_tpl    = str(user_dir / f"{post_id}.audio.%(ext)s")
    combined_tpl = str(user_dir / f"{post_id}.combined.%(ext)s")

    try:
        logging.info(f"[{user}] Attempting separate streams for {post_id}")
        download_stream(url, video_tpl, "bestvideo[height<=720]")
        download_stream(url, audio_tpl, "bestaudio/best")
        video_files = list(user_dir.glob(f"{post_id}.video.*"))
        audio_files = list(user_dir.glob(f"{post_id}.audio.*"))
        if not video_files or not audio_files:
            raise DownloadError("Missing separate streams")
        if merge_with_ffmpeg(video_files[0], audio_files[0], final_mp4):
            logging.info(f"[{user}] Merged separate streams into {final_mp4.name}")
            return True
        else:
            raise DownloadError("FFmpeg merge failed")
    except DownloadError as e:
        logging.warning(f"[{user}] Separate stream failed ({e}), falling back to combined stream")

    try:
        logging.info(f"[{user}] Downloading combined stream for {post_id}")
        download_stream(url, combined_tpl, "bv+ba/b")
        combined_files = list(user_dir.glob(f"{post_id}.combined.*"))
        for f in combined_files:
            if f.suffix.lower() in ['.mp4', '.mkv', '.webm']:
                f.rename(final_mp4)
                logging.info(f"[{user}] Downloaded combined stream as {final_mp4.name}")
                return True
        logging.error(f"[{user}] No combined stream file found for {post_id}")
    except DownloadError as ex:
        logging.error(f"[{user}] Combined stream download failed: {ex}")

    logging.warning(f"[{user}] No video available for {post_id}, skipping")
    return False

def main():
    csv_path    = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    output_root = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT

    if csv_path is None:
        logging.error(f"No CSV found for user '{TARGET_USERNAME}'. Provide CSV path or run prior step.")
        sys.exit(1)
    if not csv_path.is_file():
        logging.error(f"CSV file not found: {csv_path}")
        sys.exit(1)

    logging.info(f"CSV file: {csv_path}")
    logging.info(f"Output directory: {output_root}")
    logging.info(f"Target username: {TARGET_USERNAME}")

    output_root.mkdir(parents=True, exist_ok=True)
    existing = {f.stem for u in output_root.iterdir() if u.is_dir() for f in u.glob('*.mp4')}

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("media_type") != "video": continue
            post_id = row.get("post_id","").strip()
            user    = row.get("username","unknown").strip()
            if post_id in existing:
                logging.info(f"[{user}] {post_id}.mp4 exists, skipping")
                continue
            tweet_url = row.get("full_url") or row.get("original_href")
            if not tweet_url:
                logging.warning(f"Missing URL in row: {row}")
                continue
            if tweet_url.startswith("/"): tweet_url = "https://x.com" + tweet_url

            logging.info(f"[{user}] Processing {tweet_url}")
            try:
                if download_tweet_video(tweet_url, output_root, user, post_id):
                    existing.add(post_id)
                time.sleep(1)
            except Exception as e:
                logging.error(f"Failed {tweet_url}: {e}")

    logging.info("All downloads complete.")

if __name__ == "__main__":
    main()