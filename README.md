# 恋の二択 Instagram 自動投稿（@koi_no_nitaku）

検証用ショート14本を、Instagram に日時どおりリールとして自動投稿する仕組みです。
スパダリラボ・シロクロ観測室と同じ方式（Instagram API with Instagram Login のトークン＋GitHub Actions）です。

## しくみ

| ファイル | 役目 |
|---|---|
| `schedule.json` | 14本の予定。`id`（NN）・`kind`（reel）・`date`・`slot`（noon / night / manual）・`caption`・`video`・`cover` |
| `media/NN.mp4`・`media/NN_cover.jpg` | 投稿する動画と表紙（元の mp4 をそのまま置いています） |
| `published/NN.json` | 投稿したら1本ごとに作られる記録（media id・permalink・時刻）。**これがある本は二度と出ません** |
| `publish.py` | 予定が来ている未投稿の1本を投稿します |
| `check_schedule.py` | 予定表の検査（日付と枠の重複・ファイルの有無・キャプション2200字以内・ハッシュタグ5個以内・1行目の重複） |
| `test_pick.py` | 時刻を変えて「どの本が選ばれるか」を機械で確かめるテスト |
| `refresh_token.py` | トークン（60日）の延長。`GH_PAT` があれば Secret も書き換えます |
| `.github/workflows/post.yml` | 投稿の本体（定時起動） |
| `.github/workflows/check.yml` | push のたびに検査とテストを走らせます |

### いつ出るか

- **noon 枠は 10:00 JST から、night 枠は 18:00 JST から**出します。
- 起動は1日10回です（JST 10・11・12・13時、18・19・20・21・22・23時）。GitHub の定時起動は数時間遅れることがあるので、枠を多めに置いています。
- どの起動でも「その本の日付が来ていて、枠の開始時刻を過ぎていて、未投稿」なら **1本だけ** 出します。出した後に届いた起動は、`published/` を見て数秒で終わります。
- 遅れて日をまたいだ起動では、**前日ぶんの未投稿を先に**出します（古い順に1本ずつ）。**3日以上前の未投稿は出さず**、警告だけ出します（出すなら下の「臨時投稿」）。
- 01 は手で投稿したものとして `published/01.json`（source: manual）を置いてあり、`slot` も `manual` なので、自動では絶対に出ません。

### 二重投稿を防ぐしかけ

1. workflow の `concurrency` で同時に2つ走らないようにしています。
2. 投稿の直前に最新の main を取り込み、`published/` を見直してから対象を決め直します。
3. 投稿の直前に、Instagram 上の直近25件のキャプション1行目と照らし合わせます。同じものがあれば投稿せず、記録だけ作ります（記録の push に失敗した回の次の起動でも二重に出ません）。
4. 投稿したらすぐ `published/NN.json` を push します（失敗したら3回まで再試行）。それでも失敗したら、記録を Actions の artifact（`published-NN`）に残して workflow を失敗にします（GitHub から失敗のメールが届きます）。その時は artifact の JSON を `published/` に置いて push してください。

### AI 生成の表示

投稿のたびに `is_ai_generated=true` を付けて、Instagram の「AI info」ラベルを付けます。
Meta の公式ドキュメントに、2026-06-22 に追加された・全バージョン対象・Instagram Login でも使える、と書かれています。

- https://developers.facebook.com/documentation/instagram-platform/changelog （AI Info Label）
- https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media （`is_ai_generated`）

付けたくない時は、リポジトリの Variables に `IG_AI_LABEL=false` を入れてください。

### 動画の公開 URL

Instagram には動画と表紙の「公開 URL」を渡します。既定は GitHub Pages です。

- Pages: `https://asuka-kasai.github.io/koi-no-nitaku-sns/media/NN.mp4`（既定）
- raw: `https://raw.githubusercontent.com/asuka-kasai/koi-no-nitaku-sns/main/media/NN.mp4`

切り替えたい時は、リポジトリの Variables に `MEDIA_BASE` を入れます（末尾の / は不要）。

```bash
gh variable set MEDIA_BASE -R asuka-kasai/koi-no-nitaku-sns --body "https://raw.githubusercontent.com/asuka-kasai/koi-no-nitaku-sns/main"
gh variable delete MEDIA_BASE -R asuka-kasai/koi-no-nitaku-sns   # Pages に戻す
```

## トークンの入れ方（葛西さんの作業）

1. @koi_no_nitaku がプロアカウントであることを確かめます。
2. https://developers.facebook.com/ →「マイアプリ」→ アプリを作成（ユースケース「その他」→ タイプ「ビジネス」）。既存のアプリに Instagram を足してもかまいません。
3. 左メニュー「アプリの追加」→ Instagram →「**Instagram API setup with Instagram login**」（Facebook login の方ではありません）。
4. 「Generate access token」→ **@koi_no_nitaku で承認**します。ほかのアカウントでログイン中だと、そちらに向いて失敗します。シークレットウィンドウで @koi_no_nitaku だけログインしてから行うと確実です。
   - テスター招待が要ると言われたら、スマホの Instagram アプリ → 設定とプライバシー → ウェブサイトのアクセス許可 → テスターの招待 →「承認」まで行います。
   - 権限は `instagram_business_basic` と `instagram_business_content_publish` です。
5. 表示された `IGAA…` の文字列がトークン、同じ画面の数字が Instagram のユーザー ID です。
6. ターミナルで次を実行し、聞かれたら値を貼って Enter します（画面には表示されません）。

```bash
gh secret set IG_ACCESS_TOKEN -R asuka-kasai/koi-no-nitaku-sns
gh secret set IG_USER_ID -R asuka-kasai/koi-no-nitaku-sns
# 任意: トークンの自動延長を Secret まで反映させたい時(repo 権限の個人アクセストークン)
gh secret set GH_PAT -R asuka-kasai/koi-no-nitaku-sns
```

7. 投稿しない確認（dry-run）を走らせます。

```bash
gh workflow run post.yml -R asuka-kasai/koi-no-nitaku-sns -f dry_run=true
gh run list -R asuka-kasai/koi-no-nitaku-sns -w post.yml -L 1
gh run view -R asuka-kasai/koi-no-nitaku-sns --log $(gh run list -R asuka-kasai/koi-no-nitaku-sns -w post.yml -L 1 --json databaseId -q '.[0].databaseId') | grep -E "対象|OK|NG|キャプション"
```

時刻を変えて選ばれ方を見るなら `-f now=2026-11-26T18:05+09:00` を足します（dry-run の時だけ効きます）。

Secrets が入るまでは、定時の起動は「トークン未設定なので何もしない」で正常に終わります。
Secrets を入れた時点で、まだ出ていない本のうち日付が2日以内のものは、次の起動から古い順に1本ずつ出ます。

## 止め方

- **全部止める**: `gh workflow disable post.yml -R asuka-kasai/koi-no-nitaku-sns`（再開は `enable`）
- **1本だけ止める**: `schedule.json` からその本を消すか、日付を後ろにずらして push します（push すると検査が走ります）。
- **出した本を出さなかったことにはできません**。Instagram 上で削除・アーカイブしてください。

## 臨時投稿

日時を無視して NN を1本出します（投稿済みの本は断ります）。

```bash
gh workflow run post.yml -R asuka-kasai/koi-no-nitaku-sns -f dry_run=false -f id=05
```

まず `-f dry_run=true -f id=05` で中身を確かめてから出すのがおすすめです。

## 手元で確かめる

```bash
python3 check_schedule.py                                  # 予定表の検査
python3 test_pick.py                                       # 選ばれ方のテスト
python3 publish.py --dry-run --now "2026-11-26T18:05+09:00"  # その時刻なら何が出るか + URL の到達
```

`.env`（IG_ACCESS_TOKEN / IG_USER_ID）を置けば手元からも投稿できますが、`.env` は git に入りません（.gitignore 済み）。
