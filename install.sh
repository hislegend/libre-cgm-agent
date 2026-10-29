#!/usr/bin/env bash
# libre-cgm 설치: 가상환경 + 패키지 + 5분 자동 수집(macOS launchd / Linux systemd user timer)
# 사용: bash install.sh            (설정 파일 ~/.config/libre-cgm/config.env 를 먼저 만든다)
#       bash install.sh --no-schedule   # 자동 수집 없이 설치만
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
VENV="$REPO/.venv"
CFG="$HOME/.config/libre-cgm/config.env"

python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -r "$REPO/requirements.txt"
echo "✓ 패키지 설치"

mkdir -p "$(dirname "$CFG")"
if [ ! -f "$CFG" ]; then
  cp "$REPO/config.env.example" "$CFG"
  chmod 600 "$CFG"
  echo "→ $CFG 를 만들었다. LLU_EMAIL 을 채운 뒤 다시 실행하라."
  exit 0
fi
chmod 600 "$CFG"

[ "${1:-}" = "--no-schedule" ] && { echo "✓ 자동 수집 생략"; exit 0; }

PY="$VENV/bin/python"
SCRIPT="$REPO/libre_cgm/collect.py"
LOGDIR="$HOME/.local/share/libre-cgm"; mkdir -p "$LOGDIR"

if [ "$(uname)" = "Darwin" ]; then
  PLIST="$HOME/Library/LaunchAgents/com.libre-cgm.collect.plist"
  sed -e "s#__PY__#$PY#" -e "s#__SCRIPT__#$SCRIPT#" -e "s#__LOG__#$LOGDIR/collect.log#" \
    "$REPO/scheduler/com.libre-cgm.collect.plist" > "$PLIST"
  launchctl bootout "gui/$(id -u)/com.libre-cgm.collect" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  launchctl kickstart "gui/$(id -u)/com.libre-cgm.collect"
  echo "✓ launchd 등록 (5분 간격) · 로그 $LOGDIR/collect.log"
else
  UNIT="$HOME/.config/systemd/user"; mkdir -p "$UNIT"
  sed -e "s#__PY__#$PY#" -e "s#__SCRIPT__#$SCRIPT#" "$REPO/scheduler/libre-cgm.service" > "$UNIT/libre-cgm.service"
  cp "$REPO/scheduler/libre-cgm.timer" "$UNIT/"
  systemctl --user daemon-reload
  systemctl --user enable --now libre-cgm.timer
  echo "✓ systemd user timer 등록 (5분 간격) · 로그 journalctl --user -u libre-cgm"
fi
