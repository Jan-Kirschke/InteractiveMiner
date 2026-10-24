"""
The Lifelong Quiz - YouTube live chat reader
Reads chat the way youtube.com's own chat window does: the channel's /live page (or a watch
page) carries a chat continuation token, and get_live_chat returns new messages plus the next
token. Works from cloud servers, where YouTube answers the video player with "sign in to
confirm you're not a bot" and libraries that need the player (pytchat) fail.
"""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.parse

import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
# Skips the EU cookie consent redirect
_COOKIES = {"SOCS": "CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMwODI5LjA3X3AxGgJlbiADGgYIgJnSmgY"}
_CHAT_URL = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?prettyPrint=false"
_CLIENT_VERSION_RE = re.compile(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"')
_VIDEO_ID_RE = re.compile(r'"currentVideoEndpoint".{0,300}?"videoId":"([\w-]{11})"', re.S)
_CONT_KINDS = ("invalidationContinuationData", "timedContinuationData", "reloadContinuationData")


def page_url(channel_id: str = "", video_id: str = "") -> str:
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return f"https://www.youtube.com/channel/{channel_id}/live"


def parse_page(html: str) -> tuple[str, str, str] | None:
    """(video_id, client_version, continuation) from a live watch page, or None if no live chat."""
    marker = "ytInitialData = "
    start = html.find(marker)
    version = _CLIENT_VERSION_RE.search(html)
    if start < 0 or not version:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html, start + len(marker))
        chat = data["contents"]["twoColumnWatchNextResults"]["conversationBar"]["liveChatRenderer"]
    except (ValueError, KeyError, TypeError):
        return None
    token = live_chat_token(next_continuation(chat.get("continuations"))[0])
    if not token:
        return None
    vid = _VIDEO_ID_RE.search(html)
    return (vid.group(1) if vid else "", version.group(1), token)


_TOP_CHAT, _LIVE_CHAT = b"\x82\x01\x0c\x08\x04", b"\x82\x01\x0c\x08\x01"


def live_chat_token(token: str) -> str:
    """The page's token opens 'Top chat', which YouTube filters (repeated short messages like '1' can
    vanish). The view mode is one protobuf field (4 = top, 1 = all); switch it to 'Live chat'.
    The view menu's own tokens can't be used: they lack the video and get HTTP 400."""
    try:
        raw = base64.urlsafe_b64decode(urllib.parse.unquote(token) + "==")
    except ValueError:
        return token
    if raw.count(_TOP_CHAT) != 1:
        return token
    return base64.urlsafe_b64encode(raw.replace(_TOP_CHAT, _LIVE_CHAT)).decode()


def next_continuation(continuations: list) -> tuple[str, float]:
    """(token, seconds until YouTube wants the next poll); token is "" when the chat ended."""
    for c in continuations or []:
        for kind in _CONT_KINDS:
            if kind in c and c[kind].get("continuation"):
                return c[kind]["continuation"], int(c[kind].get("timeoutMs", 1000)) / 1000.0
    return "", 0.0


def parse_chat(response: dict) -> tuple[list[tuple[str, str, str, float, str]], str, float]:
    """([(message id, author, text, sent at, author channel id)], next token, wait seconds) from a
    get_live_chat response. authorExternalChannelId is on every text message (measured 2026-10-24
    on a public live chat; pytchat 0.5.5 reads the same key): the show's own posts carry ours."""
    lc = response.get("continuationContents", {}).get("liveChatContinuation")
    if not lc:
        return [], "", 0.0
    messages = []
    for action in lc.get("actions", []):
        item = action.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer")
        if not item:
            continue  # tickers, super chats, deletions, ...
        author = item.get("authorName", {}).get("simpleText", "").lstrip("@")
        text = "".join(r.get("text", "") for r in item.get("message", {}).get("runs", [])).strip()
        if author and text:
            sent = int(item.get("timestampUsec") or 0) / 1e6 or time.time()
            messages.append((item.get("id", ""), author, text, sent, item.get("authorExternalChannelId", "")))
    token, wait = next_continuation(lc.get("continuations"))
    return messages, token, wait


class LiveChat:
    """One live chat session. open() finds the chat, poll() returns new (author, text) pairs."""

    # YouTube always suggests 10 s, but delivers a message to a poller about 1.2 s after it was sent
    # (measured); polling every 0.5 s keeps our share of the delay small without throttling.
    MIN_WAIT, MAX_WAIT = 0.5, 0.5

    def __init__(self, url: str, session: requests.Session | None = None):
        self.url = url
        self.video_id = ""
        self._http = session or requests.Session()
        self._version = ""
        self._token = ""
        self._seen: dict[str, None] = {}   # recent message ids: YouTube sometimes delivers one twice

    def open(self) -> bool:
        resp = self._http.get(self.url, headers=_HEADERS, cookies=_COOKIES, timeout=15)
        found = parse_page(resp.text) if resp.status_code == 200 else None
        if not found:
            return False
        self.video_id, self._version, self._token = found
        self.poll()  # the first batch is chat history from before we joined: drop it
        return bool(self._token)

    @property
    def alive(self) -> bool:
        return bool(self._token)

    def poll(self) -> tuple[list[tuple[str, str, float, str]], float]:
        """New (author, text, sent at, author channel id) and how long to wait before the next poll.
        Chat ended -> alive is False."""
        body = {"context": {"client": {"clientName": "WEB", "clientVersion": self._version}},
                "continuation": self._token}
        resp = self._http.post(_CHAT_URL, json=body, headers=_HEADERS, cookies=_COOKIES, timeout=5)
        resp.raise_for_status()
        messages, self._token, wait = parse_chat(resp.json())
        fresh = []
        for msg_id, author, text, sent, channel in messages:
            if msg_id and msg_id in self._seen:
                continue
            self._seen[msg_id] = None
            fresh.append((author, text, sent, channel))
        while len(self._seen) > 2000:
            del self._seen[next(iter(self._seen))]
        return fresh, min(self.MAX_WAIT, max(self.MIN_WAIT, wait))
