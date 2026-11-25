#!/usr/bin/env python3
"""恋の二択(@koi_no_nitaku) Instagram リール自動投稿。

schedule.json のうち「日付が来ていて、その枠(slot)の開始時刻を過ぎていて、
published/NN.json が無い」ものを、古い順に **1回の起動で1本だけ** 投稿する。

  枠の開始時刻(JST): noon = 10:00 / night = 18:00
  slot が manual のもの(01)は自動では絶対に出さない。
  cron が遅れて日をまたいだ場合は、前日ぶんの未投稿が先に選ばれる(古い順なので)。
  3日以上前(今日 - date >= 3日)の未投稿は出さずに警告だけ出す。

使い方:
  python3 publish.py --plan                     # 対象を決めるだけ(API を呼ばない・数秒)
  python3 publish.py --dry-run                  # 対象決定 + 動画/表紙URLの到達確認 + キャプション表示
  python3 publish.py --dry-run --now "2026-11-26T18:05+09:00"   # 時刻を変えて選ばれ方を確かめる
  python3 publish.py                            # 本番投稿(IG_ACCESS_TOKEN / IG_USER_ID が要る)
  python3 publish.py --id 05                    # 臨時投稿(日時を無視して NN を出す。投稿済みなら断る)

標準ライブラリだけで動く(CI で pip を使わない = 起動が数秒で終わる)。
"""
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
SLOT_START = {"noon": dtime(10, 0), "night": dtime(18, 0)}
STALE_DAYS = 3   # これ以上前の未投稿は出さない

GRAPH = "https://graph.instagram.com/v21.0"
REPO = os.environ.get("GITHUB_REPOSITORY", "asuka-kasai/koi-no-nitaku-sns")
OWNER, NAME = REPO.split("/", 1)
# 動画・表紙の公開 URL の土台。既定は GitHub Pages(video/mp4 で返る)。
# raw に切り替えるなら MEDIA_BASE=https://raw.githubusercontent.com/asuka-kasai/koi-no-nitaku-sns/main
MEDIA_BASE = (os.environ.get("MEDIA_BASE") or f"https://{OWNER}.github.io/{NAME}").rstrip("/")
# AI 生成の自己申告(Meta 公式: is_ai_generated。2026-06-22 追加・全バージョン・Instagram Login でも可)
AI_LABEL = (os.environ.get("IG_AI_LABEL", "true").strip().lower() != "false")

TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IGID = os.environ.get("IG_USER_ID", "")

try:
    import certifi  # ローカル mac 用。CI には無くてよい
    SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL = ssl.create_default_context()


def _load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def out(key, val):
    """GitHub Actions のステップ出力に書く(ローカルでは何もしない)"""
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{key}={val}\n")


def load_schedule():
    return json.loads((ROOT / "schedule.json").read_text(encoding="utf-8"))


def published_ids():
    return {p.stem for p in (ROOT / "published").glob("*.json")}


def start_of(entry):
    d = date.fromisoformat(entry["date"])
    return datetime.combine(d, SLOT_START[entry["slot"]], tzinfo=JST)


def pick(schedule, done, now):
    """投稿すべき1本を返す。(entry or None, 警告のリスト)"""
    warns = []
    today = now.astimezone(JST).date()
    due = []
    for e in schedule:
        if e["id"] in done:
            continue
        if e.get("slot") not in SLOT_START:      # manual など。自動では出さない
            continue
        if start_of(e) > now:
            continue
        age = (today - date.fromisoformat(e["date"])).days
        if age >= STALE_DAYS:
            warns.append(f"{e['id']}({e['date']} {e['slot']})は{age}日前の未投稿のため自動では出しません。"
                         f"出すなら workflow_dispatch の id={e['id']} で臨時投稿してください")
            continue
        due.append(e)
    due.sort(key=lambda e: (start_of(e), e["id"]))
    return (due[0] if due else None), warns


def media_url(path):
    return f"{MEDIA_BASE}/{path}"


def head(url):
    """(status, content-type, content-length) を返す。失敗は (0, エラー, '')"""
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30, context=SSL)
        return r.status, r.headers.get("Content-Type", ""), r.headers.get("Content-Length", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), ""
    except Exception as e:
        return 0, str(e)[:80], ""


def wait_reachable(url, want_type, tries=20, interval=15):
    """Pages の配信反映待ち(push 直後は 404 のことがある)"""
    for i in range(tries):
        st, ct, _ = head(url)
        if st == 200 and ct.startswith(want_type):
            return True
        print(f"  到達待ち {i+1}/{tries}: {st} {ct} {url}")
        time.sleep(interval)
    return False


# ---------- Instagram API ----------
def _redact(s):
    return s.replace(TOKEN, "[TOKEN]") if TOKEN else s


def api(path, params, method="POST"):
    params = {**params, "access_token": TOKEN}
    if method == "GET":
        req = urllib.request.Request(f"{GRAPH}/{path}?" + urllib.parse.urlencode(params))
    else:
        req = urllib.request.Request(f"{GRAPH}/{path}", data=urllib.parse.urlencode(params).encode(), method="POST")
    try:
        return json.load(urllib.request.urlopen(req, timeout=60, context=SSL))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"IG API {e.code} ({path}): {_redact(e.read().decode(errors='replace'))[:500]}")


def first_line(caption):
    return (caption or "").strip().split("\n")[0].strip()


def already_on_ig(entry):
    """直近の投稿に同じ1行目のキャプションがあれば、その media を返す。
    published の push に失敗した回の次の起動で二重投稿しないための保険(git に頼らない照合)。"""
    res = api(f"{IGID}/media", {"fields": "id,caption,permalink,timestamp", "limit": 25}, method="GET")
    want = first_line(entry["caption"])
    for m in res.get("data", []):
        if want and first_line(m.get("caption")) == want:
            return m
    return None


def publish_reel(entry):
    params = {
        "media_type": "REELS",
        "video_url": media_url(entry["video"]),
        "cover_url": media_url(entry["cover"]),
        "caption": entry["caption"],
        "share_to_feed": "true",
    }
    if AI_LABEL:
        params["is_ai_generated"] = "true"
    cid = None
    for attempt in range(5):
        try:
            cid = api(f"{IGID}/media", params)["id"]
            break
        except RuntimeError as e:
            # 2207052 = メディアを取りに行けなかった(配信直後など)。少し待って再試行
            if "2207052" in str(e) and attempt < 4:
                print(f"  動画取得リトライ {attempt+1}/5 …")
                time.sleep(20)
                continue
            raise
    print(f"[2] コンテナ作成: {cid} / 動画処理を待ちます")
    for _ in range(80):          # 最大 約8分
        time.sleep(6)
        st = api(cid, {"fields": "status_code,status"}, method="GET")
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"コンテナが {code}: {st.get('status')}")
    else:
        raise RuntimeError("コンテナが FINISHED になりませんでした(8分)")
    mid = api(f"{IGID}/media_publish", {"creation_id": cid})["id"]
    link = ""
    try:
        link = api(mid, {"fields": "permalink"}, method="GET").get("permalink", "")
    except Exception as e:
        print(f"  permalink 取得失敗(投稿自体は成功): {e}")
    return mid, link


def write_record(entry, mid, link, source):
    rec = {"id": entry["id"], "title": entry.get("title", ""), "date": entry["date"], "slot": entry["slot"],
           "source": source, "media_id": mid, "permalink": link,
           "published_at": datetime.now(JST).isoformat(timespec="seconds"),
           "ai_label": AI_LABEL if source == "auto" else None}
    p = ROOT / "published" / f"{entry['id']}.json"
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[3] 記録: {p.relative_to(ROOT)}")
    print("RECORD_JSON=" + json.dumps(rec, ensure_ascii=False))   # push に失敗しても log から戻せるように


def main():
    _load_env()
    global TOKEN, IGID
    TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
    IGID = os.environ.get("IG_USER_ID", "")

    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="対象を決めて表示するだけ")
    ap.add_argument("--dry-run", action="store_true", help="投稿しない。URL到達とキャプションまで")
    ap.add_argument("--now", default="", help="現在時刻の上書き(ISO8601。例 2026-11-26T18:05+09:00)")
    ap.add_argument("--id", default="", help="臨時投稿する NN(日時を無視)")
    args = ap.parse_args()
    if args.now and not (args.dry_run or args.plan):
        sys.exit("--now は --dry-run / --plan と一緒にだけ使えます(本番の時刻をずらさない)")

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    schedule = load_schedule()
    done = published_ids()

    if args.id:
        nn = args.id.zfill(2)
        cand = [e for e in schedule if e["id"] == nn]
        if not cand:
            sys.exit(f"id={nn} は schedule.json にありません")
        if nn in done:
            print(f"::warning::{nn} は投稿済み(published/{nn}.json あり)。臨時投稿しません")
            out("target", "")
            return
        target, warns = cand[0], []
    else:
        target, warns = pick(schedule, done, now)
    for w in warns:
        print(f"::warning::{w}")
    print(f"現在 {now.astimezone(JST).isoformat(timespec='minutes')} JST / 投稿済み {sorted(done)}")
    if not target:
        print("投稿すべき予定はありません。終了します")
        out("target", "")
        return
    print(f"対象: {target['id']} {target.get('title','')} ({target['date']} {target['slot']})")
    out("target", target["id"])
    if args.plan:
        return

    vurl, curl = media_url(target["video"]), media_url(target["cover"])
    if args.dry_run:
        for u, want in ((vurl, "video/mp4"), (curl, "image/jpeg")):
            st, ct, ln = head(u)
            ok = "OK" if st == 200 and ct.startswith(want) else "NG"
            print(f"  [{ok}] {st} {ct} {ln}B {u}")
        print(f"AI ラベル(is_ai_generated): {'付ける' if AI_LABEL else '付けない'}")
        print(f"キャプション({len(target['caption'])}字):\n{target['caption']}")
        print("\n[dry-run] 投稿はしていません")
        return

    if not TOKEN or not IGID:
        print("::notice::IG_ACCESS_TOKEN / IG_USER_ID が未設定のため何もしません(Secrets 登録で動きます)")
        return

    print("[1] 公開 URL の到達確認")
    if not wait_reachable(vurl, "video/mp4") or not wait_reachable(curl, "image/"):
        sys.exit(f"::error::動画/表紙の URL に届きません: {vurl} / {curl}")

    dup = already_on_ig(target)
    if dup:
        print(f"::warning::{target['id']} は Instagram 上に同じキャプションの投稿があります({dup.get('permalink')})。"
              f"記録だけ作って投稿しません")
        write_record(target, dup.get("id"), dup.get("permalink", ""), "recovered_from_ig")
        out("posted", target["id"])
        return

    mid, link = publish_reel(target)
    print(f"✅ 投稿しました: {target['id']} media id {mid} {link}")
    write_record(target, mid, link, "auto")
    out("posted", target["id"])


if __name__ == "__main__":
    main()
