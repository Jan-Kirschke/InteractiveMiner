"""
The Lifelong Quiz - A 24/7 YouTube Livestream Quiz Game

Usage:
    python -m quiz.game                  # Auto-detect from config channels
    python -m quiz.game --offline        # Offline mode with fake chat bots
    python -m quiz.game VIDEO_ID         # Connects to a specific YouTube livestream

The script will:
1. Use an explicit VIDEO_ID argument if provided
2. Otherwise use VIDEO_ID from quiz/config.py if set
3. Otherwise auto-detect a livestream from the configured channels
4. Keep polling in background until a stream is found

Configure your channels in quiz/config.py:
    CHANNEL_IDS = ["UCxxxxx", ...]

Controls:
    Chat: Type 1-4 to answer, "reset" to clear your score
    Host: ESC to quit, F1 to skip current phase, F2 to toggle streaming
"""

import sys
from quiz.controller import MainGameController


def main():
    video_id = ""
    offline = "--offline" in sys.argv
    if offline:
        sys.argv.remove("--offline")

    if len(sys.argv) > 1:
        video_id = sys.argv[1]
        print(f"[Quiz] Using provided video ID: {video_id}")
    elif offline:
        print("[Quiz] Offline mode - fake chat bots + filler bots active")
    else:
        print("[Quiz] No video ID argument - will auto-detect from configured channels")

    controller = MainGameController(video_id, offline=offline)
    try:
        controller.run()
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()


if __name__ == "__main__":
    main()
