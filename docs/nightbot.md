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
| phone | 15 min | 5 | 📱 Secret answers: play on your phone at http://178.104.155.158. Nobody sees your answer and it counts the moment you tap. Link once with the !link code the page shows. |
| vote | 20 min | 10 | 🗳️ Between matches, vote the next category with 1-4. Type !rank to see your place on the weekly ladder. |
| fair | 30 min | 10 | ⚖️ Fair play: watch at the live position, one answer counts per question, no spam. Players marked [Bot] are computer opponents, not viewers. |
| sub | 30 min | 15 | 🔔 Enjoying the quiz? Subscribe and turn on notifications: live shows every day at 18:00 and 01:00 UTC. |

## Commands

Do not create `!rank`, `!card` or `!link`: the game answers those itself.

| Command | Message |
|---|---|
| !howto | Type 1, 2, 3 or 4 in chat before the timer ends. Points for correct answers, bonus for speed and streaks. Your points are saved between shows. |
| !phone | Play with secret answers on your phone: http://178.104.155.158 |
| !schedule | Live every day at 18:00 and 01:00 UTC, three hours each. |
