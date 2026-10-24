"""
The Lifelong Quiz - YouTube Data API v3 (live broadcasts) over plain REST.

YouTube no longer creates a broadcast by itself when our encoder connects, so the show creates,
binds, starts and ends its own. Setup: docs/youtube-api.md.

    python -m quiz.ytapi auth      one-time OAuth device flow (prints a URL and a code)
    python -m quiz.ytapi status    stream health and broadcast state (never the stream key)
    python -m quiz.ytapi ensure    find or create today's broadcast and make it live
    python -m quiz.ytapi end       end our live broadcast

Secrets: the stream key (QUIZ_STREAM_KEY) is compared in memory only, and neither it, an ingestion
URL nor a token is ever logged or printed.

Sources (read 2026-10-24):
  developers.google.com/identity/protocols/oauth2/limited-input-device  (device flow, errors)
  developers.google.com/youtube/data/live/reference/rest/v3/liveBroadcasts[/list|insert|bind|transition]
  developers.google.com/youtube/data/live/reference/rest/v3/liveStreams[/list]
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import threading
import time
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parent.parent
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
SCOPE = "https://www.googleapis.com/auth/youtube"

DEFAULT_TITLE = "The Lifelong Quiz · LIVE trivia, answer 1-4 in chat"
DEFAULT_DESCRIPTION = (
    "Live trivia, all day. Type 1, 2, 3 or 4 in chat to answer; the fastest right answers score most.\n"
    "Commands: !ready  !rank  !card  !crew <name>  !duel @name")
ENTERTAINMENT = "24"
AUTH_EXPIRED = "YouTube authorisation expired: run quizctl youtube-auth"

LIVE_STATES = ("live", "liveStarting")
ENDED_STATES = ("complete", "revoked")


def client_path() -> Path:
    return Path(os.environ.get("QUIZ_YT_CLIENT") or _ROOT / "secrets" / "youtube_client.json")


def token_path() -> Path:
    return Path(os.environ.get("QUIZ_YT_TOKEN") or _ROOT / "secrets" / "youtube_token.json")


def configured() -> bool:
    """The API is used only once someone authorised it (the token file exists)."""
    return token_path().is_file()


class YouTubeError(Exception):
    """An API call failed. str() carries the HTTP code, reason and message: never a secret."""

    def __init__(self, status: int, reason: str, message: str = ""):
        super().__init__(f"HTTP {status} {reason}: {message}".strip(": "))
        self.status, self.reason = status, reason


class AuthExpired(YouTubeError):
    def __init__(self):
        super().__init__(400, "invalid_grant", AUTH_EXPIRED)


class QuotaExceeded(YouTubeError):
    pass


def _write_private(path: Path, data: dict):
    """Atomically replace `path` with JSON readable by the owner only (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _load_client(path: Path) -> tuple[str, str]:
    """(client_id, client_secret) from the JSON Google Cloud downloads ({"installed": {...}} or flat)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for value in [data, *(v for v in data.values() if isinstance(v, dict))]:
        if isinstance(value, dict) and value.get("client_id"):
            return value["client_id"], value.get("client_secret", "")
    raise ValueError(f"{path.name} has no client_id: download the OAuth client JSON again")


def _iso(t: float) -> str:
    return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class YouTubeAPI:
    """Authorised calls to the YouTube Data API v3. One instance per process; thread-safe enough for
    the two threads that use it (the keeper and shutdown), since every call is independent."""

    QUOTA_PAUSE = 3600.0       # after quotaExceeded, no calls for this long (quota resets daily)
    TRANSITION_EVERY = 300.0   # at most one manual go-live per broadcast per 5 min (50 units each)

    def __init__(self, stream_key: str, client_file: Path | None = None, token_file: Path | None = None,
                 http=None, clock=time.time, log=print):
        self._key = stream_key
        self.client_file = client_file or client_path()
        self.token_file = token_file or token_path()
        self._http = http or requests.Session()
        self._clock = clock
        self._log = log
        self._lock = threading.Lock()
        self._token: dict | None = None
        self._quota_until = 0.0
        self._transitioned: dict[str, float] = {}
        self._announced: set[tuple[str, str]] = set()
        self.title = os.environ.get("QUIZ_YT_TITLE") or DEFAULT_TITLE
        self.description = os.environ.get("QUIZ_YT_DESCRIPTION") or DEFAULT_DESCRIPTION
        self.privacy = os.environ.get("QUIZ_YT_PRIVACY") or "public"

    # ---- OAuth -------------------------------------------------------------------------------
    def _client(self) -> tuple[str, str]:
        return _load_client(self.client_file)

    def _access_token(self) -> str:
        with self._lock:
            if self._token is None:
                self._token = json.loads(self.token_file.read_text(encoding="utf-8"))
            if self._token.get("expiry", 0) - 60 > self._clock() and self._token.get("access_token"):
                return self._token["access_token"]
            return self._refresh()

    def _refresh(self) -> str:
        refresh = (self._token or {}).get("refresh_token")
        if not refresh:
            raise AuthExpired()
        cid, secret = self._client()
        resp = self._http.request("POST", TOKEN_URL, data={
            "client_id": cid, "client_secret": secret,
            "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=10)
        body = _json(resp)
        if resp.status_code != 200:
            if body.get("error") == "invalid_grant":
                raise AuthExpired()
            raise YouTubeError(resp.status_code, body.get("error", "token_error"), body.get("error_description", ""))
        self._token = {**self._token, "access_token": body["access_token"],
                       "expiry": self._clock() + float(body.get("expires_in", 3600))}
        if body.get("refresh_token"):
            self._token["refresh_token"] = body["refresh_token"]
        _write_private(self.token_file, self._token)
        return self._token["access_token"]

    def device_auth(self, show=print, sleep=time.sleep) -> dict:
        """The device flow: show the URL and code, poll until the owner approves, save the token."""
        cid, secret = self._client()
        resp = self._http.request("POST", DEVICE_CODE_URL, data={"client_id": cid, "scope": SCOPE}, timeout=15)
        code = _json(resp)
        if resp.status_code != 200:
            raise YouTubeError(resp.status_code, code.get("error", "device_code_error"), code.get("error_description", ""))
        show(f"Open {code['verification_url']} and enter the code:  {code['user_code']}")
        show("Sign in with the account that owns the quiz channel, pick that channel, and allow access.")
        interval = float(code.get("interval", 5))
        deadline = self._clock() + float(code.get("expires_in", 1800))
        while self._clock() < deadline:
            sleep(interval)
            resp = self._http.request("POST", TOKEN_URL, data={
                "client_id": cid, "client_secret": secret, "device_code": code["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=15)
            body = _json(resp)
            if resp.status_code == 200:
                token = {"access_token": body["access_token"], "refresh_token": body.get("refresh_token", ""),
                         "expiry": self._clock() + float(body.get("expires_in", 3600)),
                         "scope": body.get("scope", SCOPE)}
                _write_private(self.token_file, token)
                with self._lock:
                    self._token = token
                return token
            err = body.get("error", "")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            raise YouTubeError(resp.status_code, err or "token_error", body.get("error_description", ""))
        raise YouTubeError(400, "expired_token", "the code expired before it was approved: run auth again")

    def browser_auth(self, open_url=None, timeout: float = 600) -> dict:
        """The loopback browser flow for a "Desktop app" client. Unlike the device flow, Google's web
        consent offers the brand-account chooser, so a channel without its own Google login can be
        picked. Runs on the operator's PC; the token then goes to the server (quizctl youtube-token)."""
        import base64
        import hashlib
        import http.server
        import secrets as _secrets
        import urllib.parse
        import webbrowser
        cid, secret = self._client()
        verifier = _secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = _secrets.token_urlsafe(16)
        got: dict = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if q.get("state", [""])[0] == state and ("code" in q or "error" in q):
                    got.update({k: v[0] for k, v in q.items()})
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h2>Done - you can close this tab.</h2>".encode())

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent select_account", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"})
        print("Opening the browser. If it does not open, paste this URL:\n" + url)
        (open_url or webbrowser.open)(url)
        deadline = self._clock() + timeout
        try:
            while not got and self._clock() < deadline:
                server.handle_request()
        finally:
            server.server_close()
        if "code" not in got:
            raise YouTubeError(400, got.get("error", "expired_token"), "no approval received from the browser")
        resp = self._http.request("POST", TOKEN_URL, data={
            "client_id": cid, "client_secret": secret, "code": got["code"], "code_verifier": verifier,
            "redirect_uri": redirect, "grant_type": "authorization_code"}, timeout=15)
        body = _json(resp)
        if resp.status_code != 200:
            raise YouTubeError(resp.status_code, body.get("error", "token_error"), body.get("error_description", ""))
        token = {"access_token": body["access_token"], "refresh_token": body.get("refresh_token", ""),
                 "expiry": self._clock() + float(body.get("expires_in", 3600)), "scope": body.get("scope", SCOPE)}
        _write_private(self.token_file, token)
        with self._lock:
            self._token = token
        return token

    # ---- REST --------------------------------------------------------------------------------
    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None,
             timeout: float = 15) -> dict:
        if self._clock() < self._quota_until:
            raise QuotaExceeded(403, "quotaExceeded", "paused until the daily quota resets")
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._access_token()}"}
            resp = self._http.request(method, f"{API}/{path}", params=params, json=body,
                                      headers=headers, timeout=timeout)
            if resp.status_code == 401 and attempt == 1:
                with self._lock:   # the access token was revoked or expired early: refresh once
                    self._token = {**(self._token or {}), "expiry": 0}
                continue
            break
        data = _json(resp)
        if resp.status_code >= 400:
            err = data.get("error", {}) if isinstance(data.get("error"), dict) else {}
            reason = ((err.get("errors") or [{}])[0].get("reason")) or str(data.get("error") or "error")
            message = err.get("message", "")
            if reason in ("quotaExceeded", "dailyLimitExceeded"):
                self._quota_until = self._clock() + self.QUOTA_PAUSE
                self._log(f"YouTube: daily API quota used up, pausing API calls for {int(self.QUOTA_PAUSE // 60)} min")
                raise QuotaExceeded(resp.status_code, reason, message)
            raise YouTubeError(resp.status_code, reason, message)
        return data

    # ---- streams and broadcasts --------------------------------------------------------------
    def find_stream(self) -> dict:
        """Our liveStream: the one whose stream name is QUIZ_STREAM_KEY, else the only one."""
        items = self.call("GET", "liveStreams", {"part": "id,snippet,cdn,status", "mine": "true",
                                                 "maxResults": 50}).get("items", [])
        mine = [s for s in items if self._key and
                s.get("cdn", {}).get("ingestionInfo", {}).get("streamName") == self._key]
        if not mine and len(items) == 1:
            mine = items
        if not mine:
            raise YouTubeError(404, "streamNotFound",
                               f"none of the channel's {len(items)} stream keys is QUIZ_STREAM_KEY")
        return mine[0]

    def _broadcasts(self, status: str) -> list[dict]:
        # Exactly one filter is allowed (broadcastStatus implies "mine"); the default type 'event'
        # would hide persistent broadcasts, so ask for all.
        return self.call("GET", "liveBroadcasts", {"part": "id,snippet,contentDetails,status",
                                                   "broadcastStatus": status, "broadcastType": "all",
                                                   "maxResults": 50}).get("items", [])

    def _bound(self, status: str, stream_id: str) -> dict | None:
        for b in self._broadcasts(status):
            if b.get("contentDetails", {}).get("boundStreamId") == stream_id:
                return b
        return None

    def broadcast_state(self, broadcast_id: str) -> str | None:
        """lifeCycleStatus of one broadcast (1 unit), None if it no longer exists."""
        items = self.call("GET", "liveBroadcasts", {"part": "id,status", "id": broadcast_id}).get("items", [])
        return items[0].get("status", {}).get("lifeCycleStatus") if items else None

    def stream_status(self, stream_id: str) -> str:
        items = self.call("GET", "liveStreams", {"part": "id,status", "id": stream_id}).get("items", [])
        return items[0].get("status", {}).get("streamStatus", "") if items else ""

    def _say(self, broadcast_id: str, what: str, line: str):
        if (broadcast_id, what) not in self._announced:
            self._announced.add((broadcast_id, what))
            self._log(line)

    def ensure_broadcast(self, wait_live: float = 60.0, poll: float = 10.0,
                         stop: threading.Event | None = None) -> str:
        """The id (= video id) of a broadcast bound to our stream that is live or on its way.
        Reuses an active one, starts an upcoming one, else creates and binds a new one."""
        stop = stop or threading.Event()
        stream = self.find_stream()
        sid = stream["id"]
        found = self._bound("active", sid) or self._bound("upcoming", sid)
        created = found is None
        if found:
            bid = found["id"]
            if found.get("status", {}).get("lifeCycleStatus") in LIVE_STATES:
                self._say(bid, "live", f"YouTube: broadcast {bid} is live (reused)")
                return bid
            self._say(bid, "reuse", f"YouTube: reusing broadcast {bid} "
                                    f"({found.get('status', {}).get('lifeCycleStatus', '?')})")
        else:
            if stop.is_set():
                raise YouTubeError(0, "cancelled", "shutting down")
            bid = self._insert()["id"]
            self._log(f"YouTube: created broadcast {bid} ({self.privacy})")
            self.call("POST", "liveBroadcasts/bind", {"id": bid, "streamId": sid, "part": "id,contentDetails"})
            self._log(f"YouTube: bound broadcast {bid} to stream {sid}")
        self._go_live(bid, sid, wait_live, poll, stop)
        if created:
            self._set_category(bid)
        return bid

    def _insert(self) -> dict:
        body = {
            "snippet": {"title": self.title[:100], "description": self.description,
                        "scheduledStartTime": _iso(self._clock() + 30)},   # must be in the future
            "status": {"privacyStatus": self.privacy, "selfDeclaredMadeForKids": False},
            "contentDetails": {"enableAutoStart": True, "enableAutoStop": False,
                               "latencyPreference": "ultraLow", "enableDvr": False,
                               "enableEmbed": True, "monitorStream": {"enableMonitorStream": False}},
        }
        return self.call("POST", "liveBroadcasts", {"part": "snippet,status,contentDetails"}, body)

    def _go_live(self, bid: str, sid: str, wait_live: float, poll: float, stop: threading.Event):
        """Auto-start normally takes it live; if not within wait_live while video arrives, transition."""
        deadline = self._clock() + wait_live
        while True:
            state = self.broadcast_state(bid)
            if state in LIVE_STATES:
                self._say(bid, "live", f"YouTube: broadcast {bid} is live")
                return
            if state in ENDED_STATES or state is None:
                raise YouTubeError(409, "broadcastEnded", f"broadcast {bid} is {state or 'gone'}")
            if self._clock() >= deadline or stop.is_set():
                break
            stop.wait(poll)
        if stop.is_set() or self.stream_status(sid) != "active":
            return   # no video yet: auto-start takes it live when it arrives; the keeper checks again
        if self._clock() - self._transitioned.get(bid, -1e12) < self.TRANSITION_EVERY:
            return
        self._transitioned[bid] = self._clock()
        try:
            self.call("POST", "liveBroadcasts/transition",
                      {"broadcastStatus": "live", "id": bid, "part": "id,status"})
            self._say(bid, "live", f"YouTube: broadcast {bid} is live (started by the show)")
        except YouTubeError as e:
            if e.reason != "redundantTransition":
                raise

    def _set_category(self, bid: str):
        try:
            self.call("PUT", "videos", {"part": "snippet"}, {"id": bid, "snippet": {
                "title": self.title[:100], "description": self.description, "categoryId": ENTERTAINMENT}})
        except YouTubeError as e:
            self._log(f"YouTube: could not set the category ({e})")

    def end_broadcast(self, broadcast_id: str = "", timeout: float = 5.0) -> bool:
        """Transition our live broadcast to complete. True if one was ended."""
        if not broadcast_id:
            active = self._bound("active", self.find_stream()["id"])
            if not active:
                return False
            broadcast_id = active["id"]
        try:
            self.call("POST", "liveBroadcasts/transition",
                      {"broadcastStatus": "complete", "id": broadcast_id, "part": "id,status"}, timeout=timeout)
        except YouTubeError as e:
            if e.reason in ("redundantTransition", "invalidTransition"):
                return False   # already complete, or never went live
            raise
        self._log(f"YouTube: ended broadcast {broadcast_id}")
        return True


def _json(resp) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


class BroadcastKeeper:
    """Keeps a live broadcast on our stream for as long as the show streams, on its own thread.
    on_video(video_id) is called whenever the broadcast (and so the chat) changes."""

    INTERVAL = 60.0
    AUTH_RETRY = 600.0   # after invalid_grant, check every 10 min whether someone re-authorised

    def __init__(self, api: YouTubeAPI, is_streaming, on_video, log=print):
        self.api, self._is_streaming, self._on_video, self._log = api, is_streaming, on_video, log
        self.video_id = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._auth_logged = False

    def start(self):
        self._thread = threading.Thread(target=self._run, name="youtube-keeper", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            self._stop.wait(self.check())

    def check(self) -> float:
        """One watchdog pass. Returns the seconds until the next one."""
        if not self._is_streaming():
            return 5.0 if not self.video_id else self.INTERVAL
        try:
            if self.video_id:
                state = self.api.broadcast_state(self.video_id)
                if state in LIVE_STATES:
                    return self.INTERVAL
                self._log(f"YouTube: broadcast {self.video_id} is {state or 'gone'}, not live: fixing it")
            vid = self.api.ensure_broadcast(stop=self._stop)
            self._auth_logged = False
            if vid != self.video_id and not self._stop.is_set():
                self.video_id = vid
                self._on_video(vid)
            return self.INTERVAL
        except AuthExpired:
            if not self._auth_logged:
                self._log(AUTH_EXPIRED)
                self._auth_logged = True
            with self.api._lock:
                self.api._token = None   # re-read the file next time: quizctl youtube-auth may have run
            return self.AUTH_RETRY
        except QuotaExceeded:
            return self.api.QUOTA_PAUSE
        except Exception as e:   # network trouble, 5xx, a stream not found yet: try again later
            self._log(f"YouTube: {e}")
            return self.INTERVAL

    def end(self, timeout: float = 8.0) -> threading.Thread:
        """Stop watching and end the broadcast on a daemon thread; join it for at most `timeout`."""
        self._stop.set()
        vid = self.video_id

        def _end():
            try:
                if vid:
                    self.api.end_broadcast(vid, timeout=min(5.0, timeout))
            except Exception as e:
                self._log(f"YouTube: could not end broadcast {vid} ({e})")
        t = threading.Thread(target=_end, name="youtube-end", daemon=True)
        t.start()
        return t


# ---- CLI ------------------------------------------------------------------------------------
USAGE = """usage: python -m quiz.ytapi auth|status|ensure|end
  auth     one-time OAuth device flow (prints a URL and a code)
  browser-auth  OAuth in the local browser with a "Desktop app" client (offers the brand-account chooser)
  status   stream health and broadcast state (never the stream key)
  ensure   find or create the broadcast and make it live
  end      end our live broadcast"""

def _api() -> YouTubeAPI:
    from quiz.config import YOUTUBE_STREAM_KEY   # loads .env
    return YouTubeAPI(YOUTUBE_STREAM_KEY)


def _status(api: YouTubeAPI) -> int:
    ch = api.call("GET", "channels", {"part": "snippet", "mine": "true"}).get("items", [])
    print(f"Channel: {ch[0]['snippet']['title']} ({ch[0]['id']})" if ch else "Channel: none for this account")
    streams = api.call("GET", "liveStreams", {"part": "id,snippet,cdn,status", "mine": "true",
                                              "maxResults": 50}).get("items", [])
    try:
        ours = api.find_stream()["id"]
    except YouTubeError:
        ours = ""
    for s in streams:
        st = s.get("status", {})
        tag = "  <- QUIZ_STREAM_KEY" if s["id"] == ours else ""
        print(f"Stream '{s.get('snippet', {}).get('title', '')}' ({s['id']}): {st.get('streamStatus', '?')}, "
              f"health {st.get('healthStatus', {}).get('status', '?')}{tag}")
    if not ours:
        print("No stream matches QUIZ_STREAM_KEY: set the key from the stream listed above (quizctl key).")
    for status in ("active", "upcoming"):
        for b in api._broadcasts(status):
            bound = b.get("contentDetails", {}).get("boundStreamId", "")
            print(f"Broadcast {b['id']} [{b.get('status', {}).get('lifeCycleStatus')}, "
                  f"{b.get('status', {}).get('privacyStatus')}] '{b.get('snippet', {}).get('title', '')}'"
                  f"{'  <- our stream' if ours and bound == ours else ''}")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd not in ("auth", "browser-auth", "status", "ensure", "end"):
        print(USAGE)
        return 2
    if cmd == "browser-auth":   # on the operator's PC: QUIZ_YT_CLIENT / QUIZ_YT_TOKEN point at local files
        api = YouTubeAPI("")
        try:
            api.browser_auth()
            ch = api.call("GET", "channels", {"part": "snippet", "mine": "true"}).get("items", [])
            print(f"Authorised channel: {ch[0]['snippet']['title']} ({ch[0]['id']})" if ch
                  else "Authorised, but this login has no YouTube channel")
            return 0
        except YouTubeError as e:
            print(f"YouTube: {e}")
            return 1
    api = _api()
    try:
        if cmd == "auth":
            if not api.client_file.is_file():
                print(f"Missing {api.client_file}: run quizctl youtube-client first")
                return 1
            api.device_auth()
            print(f"Authorised. Token saved to {api.token_file}.")
            return _status(api)
        if not api.token_file.is_file():
            print("YouTube API not set up: run quizctl youtube-auth (docs/youtube-api.md)")
            return 1
        if cmd == "status":
            return _status(api)
        if cmd == "ensure":
            print(f"Broadcast: https://youtu.be/{api.ensure_broadcast()}")
            return 0
        print("Ended." if api.end_broadcast() else "No live broadcast on our stream.")
        return 0
    except AuthExpired:
        print(AUTH_EXPIRED)
        return 1
    except YouTubeError as e:
        print(f"YouTube: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
