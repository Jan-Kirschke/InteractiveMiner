"""
The Lifelong Quiz - A 24/7 YouTube Livestream Quiz Game

Usage:
    python -m quiz.game                  # Auto-detect from config or fake chat mode
    python -m quiz.game VIDEO_ID         # Connects to a specific YouTube livestream

The script will:
1. Use an explicit VIDEO_ID argument if provided
2. Otherwise use VIDEO_ID from quiz/config.py if set
3. Otherwise auto-detect a livestream from the configured channel
4. Fall back to fake chat mode if nothing is found (keeps polling in background)

Configure your channel in quiz/config.py:
    CHANNEL_USERNAME = "YourChannelHandle"

Controls:
    Chat: Type 1-4 to answer, "reset" to clear your score
    Host: ESC to quit, F1 to skip current phase (debug)
"""

import sys
from quiz.controller import MainGameController


def main():
    video_id = ""
    if len(sys.argv) > 1:
        video_id = sys.argv[1]
        print(f"[Quiz] Using provided video ID: {video_id}")
    else:
        print("[Quiz] No video ID argument - will check config for channel/video settings")

    controller = MainGameController(video_id)
    try:
        controller.run()
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()


if __name__ == "__main__":
    main()
