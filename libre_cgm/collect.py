#!/usr/bin/env python3
"""FreeStyle Libre 혈당 수집기 — LibreLinkUp(보호자 계정)에서 혈당을 받아 SQLite에 쌓는다.

설정 (환경변수 또는 설정 파일 ~/.config/libre-cgm/config.env):
  LLU_EMAIL            보호자(LibreLinkUp) 계정 이메일            [필수]
  LLU_PASSWORD         비밀번호 — macOS는 키체인 사용 권장(아래)   [키체인 없을 때 필수]
  LLU_REGION           서버 지역 (AP·EU·US·JP …). 비우면 자동      [선택]
  CGM_DATA_DIR         저장 폴더 (기본 ~/.local/share/libre-cgm) [선택]
  TELEGRAM_BOT_TOKEN   위험 알림용 텔레그램 봇 토큰               [선택]
  TELEGRAM_CHAT_ID     알림 받을 chat id                          [선택]
  CGM_LOW / CGM_HIGH   알림 기준 mg/dL (기본 70 / 250)            [선택]

macOS 키체인: security add-generic-password -s libre-cgm -a "<이메일>" -w
  (LLU_PASSWORD가 없으면 키체인 service=libre-cgm 에서 읽는다)

사용:
  python collect.py           # 1회 수집 (스케줄러가 5분마다 부른다)
  python collect.py --check   # 로그인·연결만 확인
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pylibrelinkup import PyLibreLinkUp
from pylibrelinkup.api_url import APIUrl
from pylibrelinkup.exceptions import RedirectError

CONFIG_FILE = Path.home() / ".config/libre-cgm/config.env"
KEYCHAIN_SERVICE = "libre-cgm"
ALERT_COOLDOWN_MIN = 60


def load_config():
    cfg = {}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    cfg.update({k: v for k, v in os.environ.items() if k.startswith(("LLU_", "CGM_", "TELEGRAM_"))})
    return cfg


CFG = load_config()
DATA_DIR = Path(os.path.expanduser(CFG.get("CGM_DATA_DIR", "~/.local/share/libre-cgm")))
DB = DATA_DIR / "glucose.db"
STATE = DATA_DIR / "state.json"
LOW = float(CFG.get("CGM_LOW", 70))
HIGH = float(CFG.get("CGM_HIGH", 250))


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1))


def password():
    if CFG.get("LLU_PASSWORD"):
        return CFG["LLU_PASSWORD"]
    if sys.platform == "darwin":
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", CFG["LLU_EMAIL"], "-w"],
            capture_output=True, text=True,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    sys.exit("비밀번호가 없다: LLU_PASSWORD 를 설정하거나 macOS 키체인(service=libre-cgm)에 넣어라")


def client(state):
    if not CFG.get("LLU_EMAIL"):
        sys.exit("LLU_EMAIL 이 없다 (%s 또는 환경변수)" % CONFIG_FILE)
    email, pw = CFG["LLU_EMAIL"], password()
    region = APIUrl.from_string(state.get("region") or CFG.get("LLU_REGION") or "US")
    c = PyLibreLinkUp(email=email, password=pw, api_url=region)
    try:
        c.authenticate()
    except RedirectError as e:  # 계정 지역이 다르면 서버가 알려 준다
        state["region"] = e.region.name
        c = PyLibreLinkUp(email=email, password=pw, api_url=e.region)
        c.authenticate()
    state.setdefault("region", region.name)
    return c


def init_db(con):
    con.execute(
        """CREATE TABLE IF NOT EXISTS readings (
            ts_utc TEXT PRIMARY KEY,   -- 측정 시각 (UTC ISO8601)
            mgdl REAL NOT NULL,
            trend TEXT,                -- latest 값에만 (UP_FAST 등)
            is_high INTEGER,
            is_low INTEGER,
            source TEXT                -- graph | latest
        )"""
    )


def to_utc(dt):
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def notify(msg):
    tok, chat = CFG.get("TELEGRAM_BOT_TOKEN"), CFG.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("[알림] " + msg.replace("\n", " "))
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
    try:
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, data, timeout=15)
    except Exception as e:
        print("텔레그램 발송 실패: %s" % type(e).__name__)


def check_alerts(con, state, val):
    now = datetime.now(timezone.utc)
    alerts = state.setdefault("alerts", {})

    def cooled(kind):
        last = alerts.get(kind)
        return not last or now - datetime.fromisoformat(last) > timedelta(minutes=ALERT_COOLDOWN_MIN)

    if val < LOW and cooled("low"):
        notify("⚠️ 저혈당 — 현재 %d mg/dL\n당 15g(주스 반 컵·사탕 3~4개) 먹고 15분 뒤 다시 확인.\n"
               "의식이 흐리거나 떨림이 심하면 바로 119." % val)
        alerts["low"] = now.isoformat()
    if val > HIGH and cooled("high"):
        rows = con.execute(
            "SELECT mgdl FROM readings WHERE ts_utc >= ?", ((now - timedelta(minutes=30)).isoformat(),)
        ).fetchall()
        if len(rows) >= 2 and all(r[0] > HIGH for r in rows):
            notify("⚠️ 고혈당 30분 이상 — 현재 %d mg/dL\n물 마시고 가볍게 걸어라.\n"
                   "갈증·구토·숨 가쁨이 같이 있으면 응급실." % val)
            alerts["high"] = now.isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    c = client(state)
    patients = c.get_patients()
    if not patients:
        save_state(state)
        print("로그인 OK · 연결된 환자 0명 — 폰에서 초대를 보내고 LibreLinkUp 앱에서 수락했는지 확인")
        return 2
    p = patients[0]
    if args.check:
        save_state(state)
        print("로그인 OK · 연결 %d명 · 지역 %s" % (len(patients), state.get("region")))
        return 0

    con = sqlite3.connect(DB)
    init_db(con)
    raw = c._get_graph_data_json(p.patient_id).get("data", {})
    if not (raw.get("connection") or {}).get("glucoseItem"):
        save_state(state)
        print("연결 OK · 아직 혈당 값 없음 (센서 준비 60분 중이거나 폰 앱이 업로드 전)")
        return 0

    graph = c.graph(p)
    cur = c.latest(p)
    if not state.get("first_reading_sent"):
        notify("첫 혈당 수신: %d mg/dL. 자동 수집 시작." % cur.value_in_mg_per_dl)
        state["first_reading_sent"] = True
    n = 0
    for m in graph:
        n += con.execute(
            "INSERT OR IGNORE INTO readings VALUES (?,?,?,?,?,?)",
            (to_utc(m.timestamp), m.value_in_mg_per_dl, None, int(m.is_high), int(m.is_low), "graph"),
        ).rowcount
    con.execute(
        "INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?,?)",
        (to_utc(cur.timestamp), cur.value_in_mg_per_dl, cur.trend.name, int(cur.is_high), int(cur.is_low), "latest"),
    )
    con.commit()
    check_alerts(con, state, cur.value_in_mg_per_dl)
    state["last_ok"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    con.close()
    print("OK 현재 %d mg/dL %s · 새 기록 %d" % (cur.value_in_mg_per_dl, cur.trend.name, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
