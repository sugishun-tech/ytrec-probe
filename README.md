# ytrec-probe 0.3.2

対象YouTubeチャンネルの複数動画について、動画ページ右側の「次の動画 / 関連動画」に現れるチャンネルを集計するローカルツールです。

ブラウザ、動画再生、YouTube Data API、利用者が用意するAPIキーは使いません。

ただし0.3.2では、初期HTMLに右側欄が含まれない場合に限り、YouTubeのWeb画面自身が使う内部 `youtubei/v1/next` 通信を実行します。これは公式Data APIではありませんが、通信上は内部APIです。「一切APIを使わない」と書くと事実と違うため、ここは区別しています。

## 0.3.2で直した問題

0.3.0では、動画ページの `ytInitialData` に右側欄が最初から含まれると仮定していました。現在のYouTubeでは、初期HTMLには動画本体だけを入れ、右側欄を後続の `next` 応答で返す場合があります。その場合、次のエラーになっていました。

```text
No right-side recommendations were present in ytInitialData
```

0.3.2は次の順序で取得します。

1. 初期HTMLの既知の右側欄パスを読む
2. 階層だけ変更された `secondaryResults` コンテナを再帰探索する
3. 見つからない場合だけ、HTML内のクライアント設定を使って `youtubei/v1/next` を取得する
4. `next` 側でもコンテナ名が変わっていた場合、動画レンダラを保守的に探索する

そのため、Chromiumは起動せず、動画の再生終了も待ちません。

## 導入

旧版とは別ディレクトリへ展開するのが確実です。

```bash
cd /home/shun/develop
unzip ytrec_probe_v0.3.2.zip
cd ytrec_probe_v0.3.2

chmod +x install.sh run.sh
./install.sh
```

## 実行

まず3本で確認します。

```bash
./run.sh collect \
  'https://www.youtube.com/@CHANNEL_HANDLE' \
  --seeds 3 \
  --recommendations 10 \
  --output-dir output
```

問題なければ本数を増やします。

```bash
./run.sh collect \
  'https://www.youtube.com/@CHANNEL_HANDLE' \
  --seeds 12 \
  --recommendations 20 \
  --output-dir output
```

## 出力

```text
output/raw.json
output/channels.csv
output/report.html
```

`raw.json` にはシード動画ごとの取得結果、`channels.csv` と `report.html` にはチャンネル単位の集計結果が入ります。

## 主なオプション

```text
--seeds N               調査する対象チャンネル動画数
--recommendations N     各動画から取得する右側動画数
--delay SECONDS         動画ごとの待機秒数。標準1秒
--timeout SECONDS       HTTPタイムアウト。標準30秒
--locale ja-JP          言語・地域設定
--debug-dir PATH        失敗時のHTML/JSON保存先
```

旧Playwright版の `--headless`、`--show-browser`、`--fresh-profile`、`--profile-dir`、`--slow-mo` は互換目的で受け付けますが、何もしません。

## 失敗時の診断ファイル

右側欄を取得できなかった場合、次を保存します。

```text
.ytrec-debug/watch-001.html
.ytrec-debug/watch-001-next.json
```

`watch-001.html` は取得した動画ページ、`watch-001-next.json` は内部 `next` 応答です。YouTubeが再び構造を着替えた場合でも、空疎なエラー文だけを残して逃亡しない設計です。

## 測定上の意味

このツールはログインCookieや普段の視聴履歴を使用しません。したがって測っているのは、特定アカウントへ強く個人化された推薦ではなく、未ログインに近いWebクライアント条件で返る関連動画です。

一回の測定結果は時刻、地域、YouTube側の実験によって揺れます。複数日で繰り返し現れるチャンネルを重視してください。

## テスト

```bash
venv/bin/python -m pip install -e '.[test]'
venv/bin/python -m pytest -q
```

0.3.2では13件の単体テストを収録しています。


## v0.3.2

- 2026年の `lockupViewModel` で、チャンネル名が `metadataRows[0].metadataParts[0].text.content` にある形式へ対応
- `canonicalBaseUrl` がなく `browseId` しかないチャンネルリンクへ対応
- チャンネルURLが省略されても、チャンネル名が取れれば集計対象にする
- 失敗時に `watch-NNN-stats.json` を生成し、動画レンダラ数とチャンネル名解決数を記録
