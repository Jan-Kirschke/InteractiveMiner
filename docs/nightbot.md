# Nightbot for The Lifelong Quiz

Nightbot posts how-to-play reminders in the live chat. The game ignores its messages
(`CHAT_BOTS` in `quiz/config.py`), so they never count as answers.

## One-time setup (about 5 minutes)

1. Open https://nightbot.tv, choose **Login with YouTube** and sign in with the quiz channel.
2. Click **Join Channel**. In YouTube Studio, make Nightbot a moderator of the channel
   (Settings > Community > Moderators: add `Nightbot`) so its links are never held back.
3. Add the timers and commands below (Timers / Commands > Custom > Add).

## Timers

Nightbot only posts a timer when chat has had at least the given number of lines since its last
post, so a quiet chat is not spammed.

| Name | Interval | Min. chat lines | Message |
|---|---|---|---|
| howto | 10 min | 5 | 🎮 HOW TO PLAY: read the question on screen and type 1, 2, 3 or 4 in chat before the countdown ends. Fast answers and streaks earn bonus points! |
| vote | 20 min | 10 | 🗳️ Between matches, vote the next category with 1-4. Type !rank to see your place on the weekly ladder. |
| fair | 30 min | 10 | ⚖️ Fair play: watch at the live position, one answer counts per question, no spam. Players marked [Bot] are computer opponents, not viewers. |
| powers | 25 min | 10 | ⚡ Power-ups: after 5 answers in a match type !double to bet x2 on your next answer. On a 3-answer streak, !half 1 3 picks two answers for half points. !team shows your team (Gold or Teal). |
| sub | 30 min | 15 | 🔔 Enjoying the quiz? Subscribe and turn on notifications: live shows every day at 18:00 and 01:00 UTC. |

## Commands

Do not create these: the game answers them itself, on screen. Each answer is a toast; nothing is posted to chat.

| Game command | What it does | Limit |
|---|---|---|
| `!rank` | your weekly place, points, level and day streak | once per 30 s per player |
| `!card` | your player card | once per 30 s per player |
| `!team` | which team your name puts you in (Gold or Teal, for good) | once per 30 s per player |
| `!half 1 3` | the 50:50 joker: two options, half the points | once per match, from a 3-answer streak |
| `!double` (or `!x2`) | while a question runs: your answer pays x2 if right, or costs up to 20 match points if wrong | once per match, after 5 answers in it; not on Crowd Mind |

Nightbot commands:

| Command | Message |
|---|---|
| !howto | Type 1, 2, 3 or 4 in chat before the timer ends. Points for correct answers, bonus for speed and streaks. Your points are saved between shows. |
| !schedule | Live every day at 18:00 and 01:00 UTC, three hours each. |
