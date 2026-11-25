#!/usr/bin/env python3
"""schedule.json の検査。push のたびと投稿の前に CI で走る。問題があれば exit 1。

  - id の重複 / (date, slot) の重複 / 同じ日付に同じ枠が2本
  - kind は reel、slot は noon / night / manual(manual は published の記録が必須)
  - date の書式(YYYY-MM-DD)
  - 動画・表紙ファイルの有無(ディスク上 か git の索引にあれば可)・100MB 以下
  - キャプションが空でない・2200字以内
  - ハッシュタグ 5個以内(Instagram は 2025-12 から1投稿5個まで。"#2" のような数字だけの話数表記は数えない)
  - キャプション1行目の重複(同じ内容を2回出さない)

使い方: python3 check_schedule.py [schedule.json のパス]
"""
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_CAPTION = 2200
MAX_TAGS = 5
MAX_BYTES = 100 * 1024 * 1024
SLOTS = {"noon", "night", "manual"}


def real_tags(caption):
    """数字だけのもの(#1 / #2-B / #4、…)は Instagram ではタグにならないので数えない"""
    return [t for t in re.findall(r"#(\w+)", caption) if not t.isdigit()]


def tracked(path):
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", path],
                           capture_output=True, text=True)
        return r.returncode == 0
    except Exception:
        return False


def main():
    sched_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "schedule.json"
    errors, warns = [], []
    try:
        schedule = json.loads(sched_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"::error::schedule.json が読めません: {e}")
        sys.exit(1)
    done = {p.stem for p in (ROOT / "published").glob("*.json")}

    for k, n in Counter(e.get("id") for e in schedule).items():
        if n > 1:
            errors.append(f"id が重複: {k} x{n}")
    for k, n in Counter((e.get("date"), e.get("slot")) for e in schedule if e.get("slot") != "manual").items():
        if n > 1:
            errors.append(f"同じ日・同じ枠に{n}本: {k[0]} {k[1]}")
    for k, n in Counter(e.get("caption", "").strip().split("\n")[0] for e in schedule).items():
        if n > 1:
            errors.append(f"キャプション1行目が重複({n}本): 「{k[:30]}」")

    for e in schedule:
        i = e.get("id", "?")
        if not re.fullmatch(r"\d\d", str(i)):
            errors.append(f"{i}: id は2桁の数字")
        if e.get("kind") != "reel":
            errors.append(f"{i}: kind は reel のみ(今は {e.get('kind')})")
        if e.get("slot") not in SLOTS:
            errors.append(f"{i}: slot は noon / night / manual(今は {e.get('slot')})")
        if e.get("slot") == "manual" and i not in done:
            errors.append(f"{i}: slot=manual なのに published/{i}.json がありません")
        try:
            date.fromisoformat(e.get("date", ""))
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"]):
                raise ValueError
        except Exception:
            errors.append(f"{i}: date が YYYY-MM-DD ではありません({e.get('date')})")
        cap = e.get("caption", "")
        if not cap.strip():
            errors.append(f"{i}: キャプションが空")
        if len(cap) > MAX_CAPTION:
            errors.append(f"{i}: キャプション {len(cap)}字 > {MAX_CAPTION}")
        tags = real_tags(cap)
        if len(tags) > MAX_TAGS:
            errors.append(f"{i}: ハッシュタグ {len(tags)}個 > {MAX_TAGS}: {tags}")
        for key, ext in (("video", ".mp4"), ("cover", ".jpg")):
            p = e.get(key, "")
            if not p.endswith(ext) or not p.startswith("media/"):
                errors.append(f"{i}: {key} は media/…{ext}(今は {p})")
                continue
            fp = ROOT / p
            if fp.exists():
                if fp.stat().st_size > MAX_BYTES:
                    errors.append(f"{i}: {p} が100MB超({fp.stat().st_size}B)")
            elif not tracked(p):
                errors.append(f"{i}: {p} がありません")
    for d in done:
        if d not in {e.get("id") for e in schedule}:
            warns.append(f"published/{d}.json に対応する予定が schedule.json にありません")

    for w in warns:
        print(f"::warning::{w}")
    if errors:
        for x in errors:
            print(f"::error::{x}")
        print(f"NG: {len(errors)}件")
        sys.exit(1)
    pending = [e["id"] for e in schedule if e["id"] not in done]
    print(f"OK: {len(schedule)}本(未投稿 {len(pending)}本: {','.join(pending)})")


if __name__ == "__main__":
    main()
