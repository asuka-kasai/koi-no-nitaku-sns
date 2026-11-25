#!/usr/bin/env python3
"""IG 長期トークン(IGAA…・60日)を延長する。手本: ~/AVA/mbti-love-lab/sns/refresh_token.py
- ローカル: .env の IG_ACCESS_TOKEN を書き換える
- CI: GH_PAT があれば GitHub Secret IG_ACCESS_TOKEN も更新する(gh CLI)
トークンは一切表示しない。発行から24時間未満などで延長できないときは落とさず終わる。
"""
import json
import os
import ssl
import subprocess
import urllib.parse
import urllib.request

_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_p):
    for l in open(_p, encoding="utf-8"):
        s = l.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
try:
    import certifi
    SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL = ssl.create_default_context()

tok = os.environ.get("IG_ACCESS_TOKEN", "")
if not tok:
    print("IG_ACCESS_TOKEN 未設定のため延長しません")
    raise SystemExit(0)

url = "https://graph.instagram.com/refresh_access_token?" + urllib.parse.urlencode(
    {"grant_type": "ig_refresh_token", "access_token": tok})
try:
    r = json.load(urllib.request.urlopen(url, timeout=30, context=SSL))
except Exception as e:
    print("延長スキップ(まだ延長できない or 一時エラー):", str(e).replace(tok, "[TOKEN]")[:160])
    raise SystemExit(0)

new = r["access_token"]
days = round(r.get("expires_in", 0) / 86400)

if os.path.exists(_p):
    lines = [("IG_ACCESS_TOKEN=" + new) if l.startswith("IG_ACCESS_TOKEN=") else l
             for l in open(_p, encoding="utf-8").read().splitlines()]
    open(_p, "w", encoding="utf-8").write("\n".join(lines) + "\n")

pat = os.environ.get("GH_PAT")
repo = os.environ.get("GITHUB_REPOSITORY")
if pat and repo:
    subprocess.run(["gh", "secret", "set", "IG_ACCESS_TOKEN", "--body", new, "--repo", repo],
                   env={**os.environ, "GH_TOKEN": pat}, check=True)
    print(f"トークンを延長し、GitHub Secret も更新しました(有効 約{days}日)")
else:
    print(f"トークンを延長しました(有効 約{days}日)" + ("" if os.path.exists(_p) else " ※GH_PAT 未設定のため Secret は古いまま"))
