#!/usr/bin/env bash
# One-time setup of The Lifelong Quiz on a fresh Ubuntu 24.04 server (run as root).
# Usage: curl/scp this repo to the server, then: sudo bash deploy/linux/setup.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Jan-Kirschke/InteractiveMiner.git}"
BRANCH="${BRANCH:-feature/matches}"  # switch to main once merged
APP=/opt/quiz

apt-get update
apt-get install -y --no-install-recommends git python3-venv ffmpeg pulseaudio pulseaudio-utils fonts-noto-core

id quiz >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/quiz --shell /usr/sbin/nologin quiz

if [ ! -d "$APP/.git" ]; then
    git clone --branch "$BRANCH" "$REPO_URL" "$APP"
fi
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --quiet -r "$APP/requirements.txt"
mkdir -p "$APP/data"
if [ ! -f "$APP/.env" ]; then
    cp "$APP/deploy/linux/env.example" "$APP/.env"
    echo ">>> Edit $APP/.env and paste the stream key (QUIZ_STREAM_KEY)."
fi
chmod 600 "$APP/.env"
chown -R quiz:quiz "$APP"

install -m 644 "$APP/deploy/linux/quiz.service" /etc/systemd/system/quiz.service
install -m 644 "$APP/deploy/linux/quiz-start.timer" /etc/systemd/system/quiz-start.timer
install -m 644 "$APP/deploy/linux/quiz-stop.service" /etc/systemd/system/quiz-stop.service
install -m 644 "$APP/deploy/linux/quiz-stop.timer" /etc/systemd/system/quiz-stop.timer
install -m 755 "$APP/deploy/linux/quizctl" /usr/local/bin/quizctl
systemctl daemon-reload
systemctl enable --now quiz-start.timer quiz-stop.timer
systemctl list-timers 'quiz-*'
echo "Done. Test a show now with: systemctl start quiz && journalctl -u quiz -f"
