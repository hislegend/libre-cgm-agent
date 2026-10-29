#!/usr/bin/env python3
"""쌓인 혈당으로 요약·식후 반응을 계산한다. 에이전트가 해석할 숫자를 만든다.

사용:
  python report.py day [YYYY-MM-DD]          # 하루 요약 (기본: 어제)
  python report.py range --days 14           # 최근 N일 요약
  python report.py meal "YYYY-MM-DD HH:MM"   # 식사 시각 기준 식후 반응 (로컬 시각)
  python report.py now                       # 최근 값 6개

지표 (국제 CGM 합의 Battelino 2019, Diabetes Care 42:1593 기준):
  TIR  70~180 비율 (당뇨 목표 >70%) · TBR <70 (<4%), <54 (<1%) · TAR >180 (<25%), >250 (<5%)
  GMI  = 3.31 + 0.02392 × 평균(mg/dL) — 추정 당화혈색소 (14일 이상 데이터에서 의미)
  CV   = 표준편차/평균 — 변동성 (≤36% 안정)
"""
import json
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta, timezone

from collect import DB


def rows_between(start_utc, end_utc):
    con = sqlite3.connect(DB)
    r = con.execute(
        "SELECT ts_utc, mgdl FROM readings WHERE ts_utc >= ? AND ts_utc < ? ORDER BY ts_utc",
        (start_utc.isoformat(), end_utc.isoformat()),
    ).fetchall()
    con.close()
    return [(datetime.fromisoformat(t), v) for t, v in r]


def pct(vals, f):
    return round(100 * sum(1 for v in vals if f(v)) / len(vals), 1) if vals else None


def summary(rows):
    vals = [v for _, v in rows]
    if not vals:
        return {"readings": 0, "note": "데이터 없음"}
    mean = statistics.mean(vals)
    sd = statistics.pstdev(vals)
    return {
        "readings": len(vals),
        "from": rows[0][0].astimezone().isoformat(timespec="minutes"),
        "to": rows[-1][0].astimezone().isoformat(timespec="minutes"),
        "mean_mgdl": round(mean),
        "min": round(min(vals)), "max": round(max(vals)),
        "cv_pct": round(100 * sd / mean, 1),
        "gmi_pct": round(3.31 + 0.02392 * mean, 1),
        "tir_70_180_pct": pct(vals, lambda v: 70 <= v <= 180),
        "tight_70_140_pct": pct(vals, lambda v: 70 <= v <= 140),
        "tbr_lt70_pct": pct(vals, lambda v: v < 70),
        "tbr_lt54_pct": pct(vals, lambda v: v < 54),
        "tar_gt180_pct": pct(vals, lambda v: v > 180),
        "tar_gt250_pct": pct(vals, lambda v: v > 250),
    }


def local_day_bounds(day):
    start = datetime.combine(day, datetime.min.time()).astimezone()
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def meal(ts_local):
    t0 = datetime.strptime(ts_local, "%Y-%m-%d %H:%M").astimezone().astimezone(timezone.utc)
    rows = rows_between(t0 - timedelta(minutes=30), t0 + timedelta(hours=3))
    pre = [v for t, v in rows if t <= t0]
    post = [(t, v) for t, v in rows if t > t0]
    if not pre or not post:
        return {"note": "식사 전후 데이터 부족", "readings": len(rows)}
    base = pre[-1]
    peak_t, peak = max(post, key=lambda x: x[1])
    at2h = min(post, key=lambda x: abs((x[0] - t0) - timedelta(hours=2)))
    return {
        "meal_time": ts_local,
        "baseline_mgdl": round(base),
        "peak_mgdl": round(peak),
        "rise_mgdl": round(peak - base),
        "minutes_to_peak": round((peak_t - t0).total_seconds() / 60),
        "at_2h_mgdl": round(at2h[1]),
        "back_to_baseline_by_2h": at2h[1] <= base + 20,
        "note": "식후 상승폭 해석은 개인차가 크다. 공식 합의 기준은 없고, 같은 사람의 음식끼리 비교하는 데 쓴다",
    }


def main():
    a = sys.argv[1:] or ["day"]
    now = datetime.now(timezone.utc)
    if a[0] == "day":
        day = datetime.strptime(a[1], "%Y-%m-%d").date() if len(a) > 1 else (datetime.now() - timedelta(days=1)).date()
        out = summary(rows_between(*local_day_bounds(day)))
        out["day"] = str(day)
    elif a[0] == "range":
        days = int(a[a.index("--days") + 1]) if "--days" in a else 14
        out = summary(rows_between(now - timedelta(days=days), now))
        out["days"] = days
    elif a[0] == "meal":
        out = meal(a[1])
    elif a[0] == "now":
        out = [{"time": t.astimezone().isoformat(timespec="minutes"), "mgdl": round(v)}
               for t, v in rows_between(now - timedelta(hours=2), now)[-6:]]
    else:
        sys.exit(__doc__)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
