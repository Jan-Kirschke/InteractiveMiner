"""
The Lifelong Quiz - Stream Finder
Automatically finds a live YouTube stream from a channel using scrapetube.
"""

import time
import threading

try:
    import scrapetube
except ImportError:
    scrapetube = None

from quiz.config import (
    CHANNEL_USERNAME, CHANNEL_ID, CHANNEL_URL, STREAM_POLL_INTERVAL,
)


def find_live_video_id(
    channel_username: str = "",
    channel_id: str = "",
    channel_url: str = "",
) -> str | None:
    """
    Search a YouTube channel for an active livestream.
    Returns the video ID if found, or None.
    """
    if not scrapetube:
        print("[Stream] scrapetube not installed, cannot auto-detect")
        return None

    # Determine which identifier to use
    kwargs = {}
    label = ""
    if channel_username:
        # Strip @ if the user included it
        kwargs["channel_username"] = channel_username.lstrip("@")
        label = f"@{kwargs['channel_username']}"
    elif channel_id:
        kwargs["channel_id"] = channel_id
        label = channel_id
    elif channel_url:
        kwargs["channel_url"] = channel_url
        label = channel_url
    else:
        return None

    print(f"[Stream] Searching for live stream on {label}...")

    try:
        videos = scrapetube.get_channel(
            **kwargs,
            content_type="streams",
            limit=10,
            sort_by="newest",
        )

        for v in videos:
            vid_id = v.get("videoId", "")

            # Check thumbnailOverlays for LIVE badge
            overlays = v.get("thumbnailOverlays", [])
            is_live = any("LIVE" in str(o) for o in overlays)

            if is_live:
                title = ""
                title_runs = v.get("title", {}).get("runs", [])
                if title_runs:
                    title = title_runs[0].get("text", "")
                print(f"[Stream] Found live stream: {title} ({vid_id})")
                return vid_id

        print("[Stream] No active livestream found")
        return None

    except Exception as e:
        print(f"[Stream] Error searching for stream: {e}")
        return None


def resolve_video_id(
    video_id: str = "",
    channel_username: str = "",
    channel_id: str = "",
    channel_url: str = "",
) -> str:
    """
    Resolve the video ID to connect to.
    Priority: explicit video_id > auto-detect from channel > empty (fake chat).
    """
    # 1. Explicit video ID always wins
    if video_id:
        print(f"[Stream] Using provided video ID: {video_id}")
        return video_id

    # 2. Try auto-detecting from channel config
    found = find_live_video_id(channel_username, channel_id, channel_url)
    if found:
        return found

    # 3. Nothing found
    has_channel = channel_username or channel_id or channel_url
    if has_channel:
        print("[Stream] No live stream found, will keep polling in background")
    return ""


class StreamWatcher:
    """
    Background thread that polls for a new livestream if none is active.
    When a stream is found, calls the callback with the video ID.
    """

    def __init__(self, on_stream_found, channel_username="", channel_id="",
                 channel_url=""):
        self._callback = on_stream_found
        self._username = channel_username
        self._channel_id = channel_id
        self._url = channel_url
        self._running = False
        self._thread = None
        self._has_channel = bool(channel_username or channel_id or channel_url)

    def start(self):
        if not self._has_channel:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _poll_loop(self):
        while self._running:
            time.sleep(STREAM_POLL_INTERVAL)
            if not self._running:
                break
            vid = find_live_video_id(
                self._username, self._channel_id, self._url,
            )
            if vid:
                print(f"[Stream] Stream detected: {vid}")
                self._callback(vid)
                break  # Stop polling once found

    def stop(self):
        self._running = False
