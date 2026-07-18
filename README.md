# ytrec-probe 0.3.3

対象YouTubeチャンネルの複数動画について、動画ページ右側の「次の動画 / 関連動画」に現れるチャンネルを集計するローカルツールです。

ブラウザ、動画再生、YouTube Data API、利用者が用意するAPIキーは使いません。

ただし、初期HTMLに右側欄が含まれない場合はYouTubeのWeb画面自身が使う内部 `youtubei/v1/next` 通信を実行します。また、推薦データにチャンネルURLが省略されている場合だけ、各動画のoEmbed応答にある投稿者URLで補完します。どちらもAPIキーは不要ですが、HTTP通信を追加で行います。「一切APIを使わない」と書いて煙に巻くより、実際の挙動を書いておきます。

## 0.3.3で直した問題

2026年7月時点の `lockupViewModel` では、関連動画のチャンネル名は返る一方、チャンネルへの遷移コマンドが丸ごと省略されることがあります。旧版は名前だけで集計を続けたため、`raw.json` と `channels.csv` の `channel_url` が空欄になりました。

0.3.3は次のように補完します。

1. レンダラ内にチャンネルURLがあれば、そのURLを検証・正規化して使う
2. URLがない推薦だけ、動画URLをYouTube oEmbedへ渡して `author_url` を取得する
3. 同じ推薦動画が複数のシードに現れる場合は結果を再利用し、不要な通信を減らす
4. 表示名は識別子として使わず、異なる動画は個別に解決して同名チャンネルの誤結合を避ける

同梱の `tests/fixtures/sugishun_tech_2026-07-12_v0.3.2.json` は `https://www.youtube.com/@sugishun_tech` を2026年7月12日に20本×20件で取得した記録です。旧版では400件中400件のURLが空でした。この記録と `httpx.MockTransport` でoEmbed応答を再現する回帰テストにより、補完後のCSVに空URLが残らないことを確認しています。外部サービスの機嫌まで単体テストへ混ぜると、テストではなく天気占いになるためです。

## 推薦欄の取得方法

0.3.0では、動画ページの `ytInitialData` に右側欄が最初から含まれると仮定していました。現在のYouTubeでは、初期HTMLには動画本体だけを入れ、右側欄を後続の `next` 応答で返す場合があります。その場合、次のエラーになっていました。

```text
No right-side recommendations were present in ytInitialData
```

現在は次の順序で取得します。

1. 初期HTMLの既知の右側欄パスを読む
2. 階層だけ変更された `secondaryResults` コンテナを再帰探索する
3. 見つからない場合だけ、HTML内のクライアント設定を使って `youtubei/v1/next` を取得する
4. `next` 側でもコンテナ名が変わっていた場合、動画レンダラを保守的に探索する

そのため、Chromiumは起動せず、動画の再生終了も待ちません。

## 導入

旧版とは別ディレクトリへ展開するのが確実です。

```bash
cd /home/shun/develop
unzip ytrec_probe_v0.3.3.zip
cd ytrec_probe_v0.3.3

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

0.3.3では、パーサ、oEmbed補完、同名チャンネルの防御処理、収集フロー、分析、CSV出力を含む21件のテストを収録しています。指定チャンネルの同梱記録400件を使う回帰テストと、同じURLを入力する収集フローの結合テストも含みます。

実際のYouTubeへ接続する確認は、通常の実行コマンドで行えます。終了時に次のような補完件数が表示されます。

```text
[channel URLs] resolved 400/400 with 145 oEmbed request(s)
```

件数は推薦内容によって変わります。oEmbed側で削除済み・非公開・一時的な制限が返った動画は空欄のまま残り、収集全体は失敗させません。

指定チャンネルを3本×10件で取得し、生成CSVの全行にURLがあることまで検査するライブテストも同梱しています。

```bash
./experiment/test.sh
```

取得量は環境変数で変更できます。

```bash
SEEDS=20 RECOMMENDATIONS=20 ./experiment/test.sh
```

## v0.3.3

- `lockupViewModel` にチャンネル遷移コマンドがない場合、oEmbedの `author_url` で補完
- 補完通信を同じ推薦動画ごとに再利用し、表示名が同じ別チャンネルを誤結合しない設計へ変更
- チャンネルURLとして不正なホストや動画・再生リストURLをCSVへ書かないよう検証
- `@sugishun_tech` の実収集記録400件を使うCSV回帰テストを追加


## v0.3.2

- 2026年の `lockupViewModel` で、チャンネル名が `metadataRows[0].metadataParts[0].text.content` にある形式へ対応
- `canonicalBaseUrl` がなく `browseId` しかないチャンネルリンクへ対応
- チャンネルURLが省略されても、チャンネル名が取れれば集計対象にする
- 失敗時に `watch-NNN-stats.json` を生成し、動画レンダラ数とチャンネル名解決数を記録
