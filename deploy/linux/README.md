# Running the quiz on a Linux server

Two shows a day at 18:00 and 01:00 UTC, 3 hours each. They are started and stopped by systemd timers.
Pushing video to the stream key makes YouTube go live ("Stream now"), so no click in YouTube Studio is needed.

1. Rent an Ubuntu 24.04 VM. Hetzner CPX22 is the cheapest candidate; if 1080p stutters, use CPX32.
2. Copy the repo over, then run `sudo bash deploy/linux/setup.sh`.
3. Paste the stream key into `/opt/quiz/.env`.
4. Test: `sudo systemctl start quiz && journalctl -u quiz -f`, then check that the channel goes live.
   Stop with `sudo systemctl stop quiz`.
5. Change show times in `quiz-start.timer` / `quiz-stop.timer`, then rerun `setup.sh`.

Rollback: `sudo systemctl disable --now quiz-start.timer quiz-stop.timer quiz.service`.
