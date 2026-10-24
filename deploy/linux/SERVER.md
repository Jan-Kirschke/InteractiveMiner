# The Lifelong Quiz server: how to run and configure it

The quiz runs on a Hetzner cloud server. It plays the game, streams it to YouTube and reads
the chat by itself. You control it from your PC with one script.

## Everyday commands (PowerShell, in the repo folder)

```
.\scripts\quiz-server.ps1 status      # running? streaming? stream key set? next show?
.\scripts\quiz-server.ps1 start       # start a show now
.\scripts\quiz-server.ps1 stop        # end the show now
.\scripts\quiz-server.ps1 logs        # watch the live log (Ctrl+C to leave; the show keeps running)
.\scripts\quiz-server.ps1 key         # paste a new YouTube stream key (hidden)
.\scripts\quiz-server.ps1 shell       # open a terminal on the server
```

The script finds the server through two lines in the repo's `.env` file (not in git):
`QUIZ_SERVER=<server IP>` and `QUIZ_SSH_KEY=<path to your private key>`.

On the server itself, the same commands work as `quizctl status`, `quizctl start` and so on.

## Going live

1. In YouTube Studio, go to **Create → Go live → Stream**, and copy the stream key.
2. Run `.\scripts\quiz-server.ps1 key` and paste it. It is stored only on the server, readable by nobody else.
3. Set up the YouTube API once (next section). Since 24 October 2026 YouTube no longer creates a
   broadcast by itself when video arrives, so without it the stream is invisible.
4. Run `.\scripts\quiz-server.ps1 start`. Within about a minute the channel is live.
5. Run `.\scripts\quiz-server.ps1 stop` to end it, or let the schedule end it. Either way the broadcast is ended.

## YouTube API (the show makes its own broadcasts)

Click-by-click guide: [docs/youtube-api.md](../../docs/youtube-api.md). In short:

1. Google Cloud Console: create a project, enable **YouTube Data API v3**.
2. OAuth consent screen: **External**, add the scope `https://www.googleapis.com/auth/youtube`.
3. **Publish the app ("In production")**. In "Testing" the authorisation expires after 7 days.
   You will see "Google hasn't verified this app": click **Advanced > Go to … (unsafe)**.
4. Create an OAuth client ID of type **TVs and Limited Input devices** and download its JSON.
5. Then, in PowerShell:

```
.\scripts\quiz-server.ps1 youtube-client "$env:USERPROFILE\Downloads\client_secret_XXXX.json"
.\scripts\quiz-server.ps1 youtube-auth      # open the URL, enter the code, approve with the CHANNEL's account
.\scripts\quiz-server.ps1 youtube-status    # channel, stream health, broadcast state
```

If the account has several channels or a Brand Account, pick The Lifelong Quiz in the chooser.
`youtube-auth` restarts a running show so it starts managing its broadcast at once.

## Schedule

By default, shows start at **18:00 and 01:00 UTC** and run **3 hours**. In Germany that is
20:00 and 03:00 in summer, and 19:00 and 02:00 in winter.

```
.\scripts\quiz-server.ps1 schedule                      # show the current schedule
.\scripts\quiz-server.ps1 schedule "18:00 01:00" 3h     # start times (UTC, space separated) and length
.\scripts\quiz-server.ps1 schedule "19:30" 2h30m        # one show a day, 2.5 hours
.\scripts\quiz-server.ps1 schedule off                  # pause the schedule (manual start/stop only)
.\scripts\quiz-server.ps1 schedule on                   # resume it
```

A show you start by hand also ends at the next scheduled end time. Use `schedule off` if you
want it to run until you stop it.

## Settings

```
.\scripts\quiz-server.ps1 config                        # list all settings (key masked)
.\scripts\quiz-server.ps1 set QUIZ_STREAM_HEIGHT 1080   # change one
.\scripts\quiz-server.ps1 unset QUIZ_STREAM_BITRATE     # back to the default
```

A change restarts a running show (viewers see a short interruption), or applies from the next show.

| Setting | Server value | What it does |
|---|---|---|
| `QUIZ_STREAM_HEIGHT` | `720` | Output resolution: `720` or `1080`. 1080 needs about twice the CPU; on this server, check `status` and the log for dropped frames after switching. |
| `QUIZ_STREAM_BITRATE` | `3000k` | Video bitrate. YouTube's guidance is roughly 1500k–4000k for 720p30 and 3000k–6000k for 1080p30. Unset it to use 3000k at 720p or 6000k at 1080p. |
| `QUIZ_AUDIO_GAIN_DB` | `3` | Makes the game sound louder on stream, in dB, with a limiter so it never clips. `0` = untouched. |
| `QUIZ_CHANNEL_IDS` | Lifelong Quiz | Which YouTube channel's live chat to read (comma separated channel IDs). Must be the channel the stream key belongs to. |
| `QUIZ_VIDEO_ID` | (empty) | Read chat from this exact live video instead of finding it automatically. |
| `QUIZ_LOBBY_SECONDS` | `30` | Lobby length (category vote, `!ready`). |
| `QUIZ_QUESTION_SECONDS` | `20` | Time to answer a question (the lightning question stays at 12). |
| `QUIZ_LATE_SECONDS` | `4` | "Time's up" phase in which late chat answers still count (YouTube chat lags the video). |
| `QUIZ_REVEAL_SECONDS` | `8` | How long the answer reveal stays on screen. |
| `QUIZ_PODIUM_SECONDS` | `14` | How long the podium stays on screen. |
| `QUIZ_MIN_PLAYERS` | `4` | Bots fill each match until this many real players answer. `0` = never any bots. Bots are labelled and never ranked. |
| `QUIZ_STREAM_KEY` | (secret) | Set it with the `key` command, never with `set`. |
| `QUIZ_YT_PRIVACY` | `public` | Privacy of the broadcasts the show creates: `public`, `unlisted` or `private`. |
| `QUIZ_YT_TITLE` | The Lifelong Quiz · LIVE trivia, answer 1-4 in chat | Title of new broadcasts. |
| `QUIZ_YT_DESCRIPTION` | how to play | Description of new broadcasts. |

Leave `QUIZ_AUDIO_INPUT`, `SDL_AUDIODRIVER` and `PULSE_SINK` as they are: they route the game sound into the stream.

## Questions

Questions come from Open Trivia DB plus the packs in `quiz/packs/`. To add your own, put a
JSON or CSV pack in `quiz/packs/` (format in `quiz/import_questions.py`), commit and push, then:

```
.\scripts\quiz-server.ps1 update
```

`update` pulls the latest code from GitHub (branch `feature/matches`) and restarts a running show.

## When something looks wrong

- **Channel not live:** run `status`. Check that the stream key is set, then run `logs` and look for `[Broadcast]` lines.
  A rejected key shows as FFmpeg errors followed by restarts with growing pauses (5 s up to 60 s).
  Then run `youtube-status` and look for `YouTube:` lines in `logs`; see the troubleshooting list in
  [docs/youtube-api.md](../../docs/youtube-api.md) (expired authorisation, quota, wrong channel).
- **"chat offline" on screen:** the stream is live but chat is not connected yet. It retries every
  20 seconds; a fresh stream can take a minute to show up on the channel page.
- **Start over:** run `restart`. The scores live in `/opt/quiz/data/quiz_data.db` and survive restarts and updates.

## Costs and switching off

The server (Hetzner CPX22) costs the same whether a show runs or not. To stop paying, delete
it in the Hetzner console (Servers → quiz → Delete). Scores on it are lost unless you copy
`/opt/quiz/data/quiz_data.db` off first.
