#!/usr/bin/env python3
"""publish.pick() の選ばれ方を、時刻を変えて機械で確かめる(投稿も API も使わない)。
python3 test_pick.py        # 失敗があれば exit 1
python3 test_pick.py --md   # 結果を Markdown の表で出す(報告用)
"""
import sys
from datetime import datetime, timedelta

import publish
from publish import JST, pick, start_of

S = publish.load_schedule()
AUTO = [e for e in S if e["slot"] in publish.SLOT_START]
fails, rows = [], []


def T(s):
    return datetime.fromisoformat(s).replace(tzinfo=JST) if "+" not in s else datetime.fromisoformat(s)


def check(name, now, done, want, want_warn=None):
    got, warns = pick(S, set(done), now)
    gid = got["id"] if got else "なし"
    ok = gid == want and (want_warn is None or any(want_warn in w for w in warns))
    rows.append((name, now.strftime("%m/%d %H:%M"), ",".join(sorted(done)) or "-", want, gid,
                 "警告あり" if warns else "", "OK" if ok else "NG"))
    if not ok:
        fails.append(f"{name}: want {want} got {gid} warns={warns}")


# 1) 14本それぞれ: 枠の開始+5分で選ばれる / 開始-1分では選ばれない(それより前は全部投稿済みとする)
for i, e in enumerate(AUTO):
    before = {"01"} | {x["id"] for x in AUTO[:i]}
    st = start_of(e)
    check(f"{e['id']} 開始+5分", st + timedelta(minutes=5), before, e["id"])
    check(f"{e['id']} 開始-1分", st - timedelta(minutes=1), before, "なし")
    check(f"{e['id']} 当日23:59", st.replace(hour=23, minute=59), before, e["id"])

# 2) noon と night が同じ日: 取り違えない
check("11/28 昼(04だけ)", T("2026-11-28T11:00"), {"01", "02", "03"}, "04")
check("11/28 17:59(05はまだ)", T("2026-11-28T17:59"), {"01", "02", "03", "04"}, "なし")
check("11/28 夜(04済→05)", T("2026-11-28T18:05"), {"01", "02", "03", "04"}, "05")
check("11/28 夜(04が未投稿→04が先)", T("2026-11-28T18:05"), {"01", "02", "03"}, "04")
check("12/01 昼", T("2026-12-01T10:00"), {"01"} | {f"{n:02d}" for n in range(2, 8)}, "08")
check("12/03 夜(11済→12)", T("2026-12-03T22:30"), {"01"} | {f"{n:02d}" for n in range(2, 12)}, "12")

# 3) 01 は選ばれない(published/01.json が消えても manual なので出ない)
check("01 当日(記録あり)", T("2026-11-25T20:00"), {"01"}, "なし")
check("01 当日(記録が消えても)", T("2026-11-25T20:00"), set(), "なし")

# 4) 日またぎ: 遅れて翌日0〜2時台に起動 → 前日ぶんを先に出す
check("11/27 01:30(02が未投稿)", T("2026-11-27T01:30"), {"01"}, "02")
check("11/28 00:40(02,03未投稿→古い02)", T("2026-11-28T00:40"), {"01"}, "02")
check("11/29 02:00(04,05未投稿→04)", T("2026-11-29T02:00"), {"01", "02", "03"}, "04")
# 5) 3日以上前は出さない(警告)
check("11/29 18:05(02が3日前)", T("2026-11-29T18:05"), {"01"}, "03", want_warn="02")
check("12/06 20:00(14の翌日)", T("2026-12-06T20:00"), {"01"} | {f"{n:02d}" for n in range(2, 14)}, "14")
check("12/08 20:00(14が3日前)", T("2026-12-08T20:00"), {"01"} | {f"{n:02d}" for n in range(2, 14)}, "なし",
      want_warn="14")
check("全部済み", T("2026-12-05T23:00"), {e["id"] for e in S}, "なし")


# 6) 通しの模擬: cron の時刻(JST 10-13時・18-23時)に毎回起動し、出たら記録する。
#    遅れ 0h / 3h / 7.5h の3通り。各本が1回だけ、正しい日(遅れ時は翌未明まで)・開始時刻以降に出ること
CRON_JST = [10, 11, 12, 13, 18, 19, 20, 21, 22, 23]
for delay in (0, 3, 7.5):
    done, posted = {"01"}, {}
    day = datetime(2026, 11, 25, tzinfo=JST)
    while day < datetime(2026, 12, 8, tzinfo=JST):
        for h in CRON_JST:
            now = day.replace(hour=h) + timedelta(hours=delay)
            got, _ = pick(S, done, now)
            if got:
                if got["id"] in done:
                    fails.append(f"二度選ばれた {got['id']}")
                done.add(got["id"])
                posted[got["id"]] = now
        day += timedelta(days=1)
    ok = len(posted) == 13
    for e in AUTO:
        t = posted.get(e["id"])
        if not t or t < start_of(e) or (t - start_of(e)) > timedelta(hours=14):
            ok = False
            fails.append(f"遅れ{delay}h: {e['id']} が {t} に出た(開始 {start_of(e)})")
    late = max((posted[e['id']] - start_of(e)) for e in AUTO if e["id"] in posted)
    rows.append((f"通し模擬 遅れ{delay}h", "11/25〜12/07", "01", "13本×1回", f"{len(posted)}本",
                 f"最大遅れ {late}", "OK" if ok else "NG"))
    if delay == 7.5:
        sim = posted

if "--md" in sys.argv:
    print("| ケース | 現在(JST) | 投稿済み | 期待 | 結果 | 備考 | 判定 |\n|---|---|---|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(r) + " |")
    print("\n遅れ7.5hの模擬で実際に出る時刻:")
    for k in sorted(sim):
        print(f"- {k}: {sim[k].strftime('%m/%d %H:%M')}")
else:
    for r in rows:
        print("  ".join(r))
if fails:
    print("\n".join("::error::" + f for f in fails))
    sys.exit(1)
print(f"OK: {len(rows)}ケース")
