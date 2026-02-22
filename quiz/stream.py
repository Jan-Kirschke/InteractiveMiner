"""
The Lifelong Quiz - Stream Finder
Automatically finds a live YouTube stream from one of the configured channels.

Detection methods (tried in order):
1. Direct HTTP fetch of channel /live page (most reliable)
2. scrapetube channel scan (fallback)

Note: Includes EU cookie consent bypass (required for YouTube in EU countries).
"""

import re
import time
import threading

try:
    import requests as _requests
except ImportError:
    _requests = None

try:
    import scrapetube
except ImportError:
    scrapetube = None

from quiz.config import CHANNEL_IDS, STREAM_POLL_INTERVAL

# Browser-like headers so YouTube doesn't reject the request
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Cookie to bypass YouTube EU consent page (GDPR redirect)
_COOKIES = {
    "SOCS": "CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMwODI5LjA3X3AxGgJlbiADGgYIgJnSmgY",
}

# Regex patterns for YouTube page parsing
_VIDEO_ID_RE = re.compile(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"')
_IS_LIVE_RE = re.compile(r'"isLive"\s*:\s*true', re.IGNORECASE)
_IS_LIVE_NOW_RE = re.compile(r'"isLiveNow"\s*:\s*true', re.IGNORECASE)
_IS_LIVE_CONTENT_RE = re.compile(r'"isLiveContent"\s*:\s*true', re.IGNORECASE)
_LIVE_BADGE_RE = re.compile(r'BADGE_STYLE_TYPE_LIVE_NOW')


def _find_live_via_http(channel_id: str) -> str | None:
    """
    Find live video ID by fetching the channel's /live page.
    YouTube's /live endpoint shows the current livestream for a channel.
    Falls back to /streams tab if /live doesn't find anything.
    """
    if not _requests:
        return None

    # Method A: Check /live page (shows currently active stream)
    vid = _check_channel_page(channel_id, "live")
    if vid:
        return vid

    # Method B: Check /streams tab (shows all streams including currently live)
    vid = _check_channel_page(channel_id, "streams")
    if vid:
        return vid

    return None


def _check_channel_page(channel_id: str, tab: str) -> str | None:
    """Fetch a channel tab page and look for a live stream video ID."""
    url = f"https://www.youtube.com/channel/{channel_id}/{tab}"
    try:
        resp = _requests.get(url, timeout=15, headers=_HEADERS, cookies=_COOKIES)
        if resp.status_code != 200:
            print(f"[Stream] HTTP {resp.status_code} for {channel_id}/{tab}")
            return None

        # Check if we got redirected to consent page (shouldn't happen with cookie)
        if "consent.youtube.com" in resp.url:
            print(f"[Stream] Consent redirect on {channel_id}/{tab} (cookie expired)")
            return None

        text = resp.text
        match = _VIDEO_ID_RE.search(text)
        if not match:
            return None

        vid = match.group(1)

        # On the /live tab, ANY video found is a live/upcoming stream.
        # YouTube only shows live content on this endpoint.
        if tab == "live":
            # Check for explicit live indicators for better logging
            is_live_now = bool(_IS_LIVE_NOW_RE.search(text) or _IS_LIVE_RE.search(text))
            has_live_badge = bool(_LIVE_BADGE_RE.search(text))
            if is_live_now or has_live_badge:
                print(f"[Stream] Found ACTIVE live stream: {vid} on {channel_id}")
            else:
                print(f"[Stream] Found live stream video: {vid} on {channel_id} (may be starting)")
            return vid

        # On /streams tab, require a LIVE badge since it lists past streams too
        has_live_badge = bool(_LIVE_BADGE_RE.search(text))
        is_live_now = bool(_IS_LIVE_NOW_RE.search(text) or _IS_LIVE_RE.search(text))
        if has_live_badge or is_live_now:
            print(f"[Stream] Found ACTIVE stream on /streams tab: {vid}")
            return vid

    except Exception as e:
        print(f"[Stream] HTTP check failed for {channel_id}/{tab}: {e}")

    return None


def _find_live_via_scrapetube(channel_id: str) -> str | None:
    """Fallback: use scrapetube to search for live streams on a channel."""
    if not scrapetube:
        return None

    try:
        videos = scrapetube.get_channel(
            channel_id=channel_id,
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
                print(f"[Stream] scrapetube found live stream: {title} ({vid_id})")
                return vid_id

    except Exception as e:
        print(f"[Stream] scrapetube error for {channel_id}: {e}")

    return None


def find_live_video_id(channel_ids: list[str] | None = None) -> str | None:
    """
    Search YouTube channels for an active livestream.
    Tries HTTP /live page first (fast, reliable), then scrapetube fallback.
    """
    if not channel_ids:
        return None

    # Method 1: Direct HTTP fetch (preferred — handles EU consent)
    for cid in channel_ids:
        print(f"[Stream] Checking {cid} via HTTP...")
        vid = _find_live_via_http(cid)
        if vid:
            return vid

    # Method 2: scrapetube fallback
    if scrapetube:
        for cid in channel_ids:
            print(f"[Stream] Checking {cid} via scrapetube...")
            vid = _find_live_via_scrapetube(cid)
            if vid:
                return vid
    elif not _requests:
        print("[Stream] Neither requests nor scrapetube available for auto-detection")

    print("[Stream] No active livestream found on any channel")
    return None


def resolve_video_id(
    video_id: str = "",
    channel_ids: list[str] | None = None,
) -> str:
    """
    Resolve the video ID to connect to.
    Priority: explicit video_id > auto-detect from channels > empty (waiting mode).
    """
    if video_id:
        print(f"[Stream] Using provided video ID: {video_id}")
        return video_id

    found = find_live_video_id(channel_ids)
    if found:
        return found

    if channel_ids:
        print("[Stream] No live stream found, will keep polling in background")
    return ""


class StreamWatcher:
    """
    Background thread that polls configured channels for a new livestream.
    When a stream is found, calls the callback with the video ID.
    """

    def __init__(self, on_stream_found, channel_ids: list[str] | None = None):
        self._callback = on_stream_found
        self._channel_ids = channel_ids or []
        self._running = False
        self._thread = None

    def start(self):
        if not self._channel_ids:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print(f"[Stream] Watcher started, polling every {STREAM_POLL_INTERVAL}s")

    def _poll_loop(self):
        while self._running:
            time.sleep(STREAM_POLL_INTERVAL)
            if not self._running:
                break
            vid = find_live_video_id(self._channel_ids)
            if vid:
                print(f"[Stream] Stream detected: {vid}")
                self._callback(vid)
                break  # Stop polling once found

    def stop(self):
        self._running = False
