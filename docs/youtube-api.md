# YouTube API: the show makes its own broadcasts

Since 24 October 2026 YouTube no longer creates a live broadcast by itself when our encoder
connects: the video arrives, but nobody can watch it. With the YouTube Data API set up, the
show does it itself, with no clicks in YouTube Studio:

- at start it reuses a live or upcoming broadcast on our stream key, or creates a new public one and binds it;
- it goes live automatically when the video arrives (auto-start), or the show starts it after about a minute;
- it checks the broadcast every minute; if YouTube ends it while we stream, a new one is made and chat follows;
- at the scheduled end (or `stop`) the broadcast is ended.

Without the setup below, everything works as before.

## One-time setup (about 10 minutes)

Use the Google account that owns the quiz channel (or manages its Brand Account).

### 1. Create a Google Cloud project
1. Open <https://console.cloud.google.com/> and sign in.
2. Click the project picker at the top left, then **New project**.
3. Name it `Lifelong Quiz`, then click **Create**. Select it in the project picker once it is ready.

### 2. Enable the YouTube Data API v3
1. Open **APIs & Services > Library** (or search "Library" at the top).
2. Search for **YouTube Data API v3**, open it, and click **Enable**.

### 3. Set up the OAuth consent screen
Google calls this **Google Auth Platform** in newer consoles and **OAuth consent screen** in older ones.
1. Open **APIs & Services > OAuth consent screen**. If asked, click **Get started**.
2. App name: `Lifelong Quiz`. User support email: your address. Click **Next**.
3. Audience: choose **External**. Click **Next**.
4. Contact information: your address. Click **Next**, agree to the policy, then **Create**.
5. Open **Data Access** (older consoles: the **Scopes** step), click **Add or remove scopes**, tick
   `https://www.googleapis.com/auth/youtube` ("Manage your YouTube account"), or paste it under
   "Manually add scopes". Then click **Update** and **Save**.

### 4. IMPORTANT: publish the app ("In production")
1. Open **Audience** (older consoles: the consent screen's main page).
2. Under **Publishing status: Testing**, click **Publish app**, then **Confirm**. It must say **In production**.

Why this matters: while the app is in **Testing**, Google lets the authorisation expire after
**7 days**. The show would then silently stop creating broadcasts a week later.

You do not need Google's verification. Because the app is unverified, the approval page in step 7
shows **"Google hasn't verified this app"**. That is expected: it is your own app. Click
**Advanced**, then **Go to Lifelong Quiz (unsafe)**.

### 5. Create the OAuth client and download it
1. Open **Clients** (older consoles: **APIs & Services > Credentials > Create credentials > OAuth client ID**).
2. Click **Create client**. Application type: **TVs and Limited Input devices**. Name: `quiz server`.
3. Click **Create**, then **Download JSON** (the download icon next to the client). The file is
   named like `client_secret_....json`. Keep it private: it identifies the app.

### 6. Send the client to the server
In PowerShell, in the repo folder:
```
.\scripts\quiz-server.ps1 youtube-client "$env:USERPROFILE\Downloads\client_secret_XXXX.json"
```
It should print `OAuth client saved. Next: quizctl youtube-auth`.
The file goes to `/opt/quiz/secrets/youtube_client.json`, readable only by the quiz user.

### 7. Authorise the channel
```
.\scripts\quiz-server.ps1 youtube-auth
```
1. It prints a line like `Open https://www.google.com/device and enter the code:  ABCD-EFGH`.
2. Open that address in any browser, type the code, and sign in with the **channel's** Google account.
3. If the account has several channels or the quiz channel is a **Brand Account**, a chooser
   appears: pick **The Lifelong Quiz**. Picking another channel makes the show manage that one.
4. On "Google hasn't verified this app", click **Advanced > Go to Lifelong Quiz (unsafe)**, then **Allow**.
5. The command finishes by itself, prints the channel and its streams, and restarts a running show.

### 8. Check it
```
.\scripts\quiz-server.ps1 youtube-status
```
You should see:
- `Channel: The Lifelong Quiz (UC...)`;
- one stream marked `<- QUIZ_STREAM_KEY`, which is `active` with health `good` while a show runs;
- during a show, one broadcast `[live, public]` marked `<- our stream`.

During a show, `logs` shows lines like:
```
YouTube: created broadcast AbCdEfGhIjK (public)
YouTube: bound broadcast AbCdEfGhIjK to stream ...
YouTube: broadcast AbCdEfGhIjK is live
YouTube: chat pinned to video AbCdEfGhIjK
YouTube: ended broadcast AbCdEfGhIjK
```

## Settings

| Setting | Default | What it does |
|---|---|---|
| `QUIZ_YT_TITLE` | `The Lifelong Quiz · LIVE trivia, answer 1-4 in chat` | Title of new broadcasts (max 100 characters) |
| `QUIZ_YT_DESCRIPTION` | how to play | Description of new broadcasts |
| `QUIZ_YT_PRIVACY` | `public` | `public`, `unlisted` or `private` |
| `QUIZ_YT_CLIENT`, `QUIZ_YT_TOKEN` | `secrets/youtube_client.json`, `secrets/youtube_token.json` | File locations; leave as they are |
| `QUIZ_CHAT_TIPS_MINUTES` | `9` | Minutes between the show's chat tips; `0` turns tips off (`!friends` replies stay on) |

Change them with `.\scripts\quiz-server.ps1 set QUIZ_YT_PRIVACY unlisted`. They apply to the next new broadcast.

## The show posts in its own chat

With the token set up, the show also writes in the live chat, as the channel (`quiz/chatpost.py`):

- **Tips**: every `QUIZ_CHAT_TIPS_MINUTES` (default 9) one rotating tip about `!friend`/`!friends`,
  `!duel @name` + `!accept`, `!crew`, `!team`, `!half`, `!double`, `!rank`/`!card`. The first tip comes
  one interval after the show goes live, so restarts do not spam.
- **`!friends` replies**: requests are collected and answered together, at most one message every
  25 s and once per player every 2 minutes, each message at most 200 characters.

The chat reader ignores messages from our own channel (it learns the id from the broadcast), so
the show never answers itself or counts its own posts as plays.

Quota (Google's docs, read 2026-10-24): a chat post (`liveChatMessages.insert`) costs **20 units**
([insert reference](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/insert),
[quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost)); looking up the
broadcast's chat (`liveBroadcasts.list`) costs 1. The project has 10,000 units a day, reset at
midnight Pacific time. Chat posts get at most **4,000 units a day (200 posts)**, of which tips may
use 3,000 so 1,000 always stay for `!friends` replies; at least 6,000 stay for the broadcast itself.
Six live hours with a tip every 9 minutes use about 800 units. When the budget is spent, the rest of
the day's posts are dropped (the log says so once). The budget is counted in memory, so a restart
starts the count again.

When YouTube answers `quotaExceeded`, posting stops until midnight Pacific time; `rateLimitExceeded`
pauses 1 minute, doubling up to 15; `forbidden` pauses an hour; `liveChatEnded` stops posting until
the next broadcast. The game never waits for any of this: posts go out on their own thread.

## Troubleshooting

- **`YouTube authorisation expired: run quizctl youtube-auth`**: Google revoked the
  authorisation (`invalid_grant`). Usual causes: the app is still in **Testing** (step 4: publish it,
  then authorise again), the account's password changed, or access was removed at
  <https://myaccount.google.com/permissions>. Fix: run `youtube-auth` again. The show picks the
  new authorisation up within 10 minutes, or at once through the restart that `youtube-auth` does.
- **`daily API quota used up`**: the project has 10,000 units a day; a normal day uses well under
  1,000 (creating a broadcast is about 200, each minute of checking is 1). The show pauses API calls
  for an hour and keeps streaming. Quota resets at midnight Pacific time. If it keeps happening,
  look in `logs` for a broadcast being re-created over and over.
- **Wrong channel** (`youtube-status` shows another channel, or `No stream matches QUIZ_STREAM_KEY`):
  run `youtube-auth` again and pick The Lifelong Quiz in the channel chooser. If the channel is right
  but no stream matches, the stream key on the server belongs to another channel: copy the key from
  YouTube Studio (**Create > Go live > Stream**) and set it with `key`.
- **`liveStreamingNotEnabled`, `insufficientLivePermissions` or a 403 on `liveBroadcasts`**: live
  streaming is not enabled for this channel or this account is not its owner or manager. Check
  <https://www.youtube.com/features>. Enabling live streaming can take 24 hours.
- **The broadcast exists but stays "ready"**: no video reaches YouTube. Check `status` and look for
  `[Broadcast]` FFmpeg errors in `logs`.
- **Each stop or restart makes a new video**: by design, `stop`, `restart`, `update` and the
  scheduled end all end the broadcast; the next start creates a fresh one with a new link.
- **Turn it off**: delete `/opt/quiz/secrets/youtube_token.json` on the server (`shell`) and
  `restart`. The show then behaves as before.
