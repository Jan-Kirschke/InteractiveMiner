"""
Downloads FFmpeg essentials build for Windows from gyan.dev.
Extracts ffmpeg.exe into the scripts/ directory.
"""

import os
import sys
import zipfile
import urllib.request
import shutil

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_EXE = os.path.join(SCRIPTS_DIR, "ffmpeg.exe")
DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def download_ffmpeg():
    if os.path.exists(FFMPEG_EXE):
        print(f"[FFmpeg] Already present at {FFMPEG_EXE}")
        return FFMPEG_EXE

    zip_path = os.path.join(SCRIPTS_DIR, "ffmpeg_download.zip")
    extract_dir = os.path.join(SCRIPTS_DIR, "_ffmpeg_temp")

    print(f"[FFmpeg] Downloading from gyan.dev (this may take a minute)...")
    try:
        urllib.request.urlretrieve(DOWNLOAD_URL, zip_path, _progress_hook)
        print()  # newline after progress
    except Exception as e:
        print(f"\n[FFmpeg] Download failed: {e}")
        print("[FFmpeg] Please download manually from https://www.gyan.dev/ffmpeg/builds/")
        print(f"[FFmpeg] Place ffmpeg.exe in: {SCRIPTS_DIR}")
        return None

    print("[FFmpeg] Extracting ffmpeg.exe...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Find ffmpeg.exe inside the zip (it's in a subdirectory)
            ffmpeg_entry = None
            for name in zf.namelist():
                if name.endswith("bin/ffmpeg.exe"):
                    ffmpeg_entry = name
                    break

            if not ffmpeg_entry:
                print("[FFmpeg] Could not find ffmpeg.exe in archive")
                return None

            # Extract to temp dir then move
            os.makedirs(extract_dir, exist_ok=True)
            zf.extract(ffmpeg_entry, extract_dir)
            extracted_path = os.path.join(extract_dir, ffmpeg_entry)
            shutil.move(extracted_path, FFMPEG_EXE)

        print(f"[FFmpeg] Installed to {FFMPEG_EXE}")
        return FFMPEG_EXE

    finally:
        # Cleanup
        if os.path.exists(zip_path):
            os.remove(zip_path)
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)


def _progress_hook(block_num, block_size, total_size):
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        sys.stdout.write(f"\r[FFmpeg] {mb:.1f}/{total_mb:.1f} MB ({pct}%)")
        sys.stdout.flush()


if __name__ == "__main__":
    result = download_ffmpeg()
    if result:
        print(f"[FFmpeg] Ready: {result}")
    else:
        print("[FFmpeg] Installation failed")
        sys.exit(1)
