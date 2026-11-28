# ICHIGYO GPT版の初期設定

この版では、執筆を担当するGPTが返した文章を、ICHIGYOの個別処理に読み込ませます。文章の受け渡しにはモデルのAPIキーを使いません。記事作成や競合調査の一括実行は準備中です。

## 1. 部品を開く

Python 3 と OpenSSL が使える環境で、`gpt/v1` の `ichigyo_set.enc` を用意します。部品の合言葉は実行環境の `ICHIGYO_PASS` に登録してください。チャット、手順書、リポジトリには貼り付けません。

リポジトリの外に、自分だけが使える作業フォルダを作ります。以下は Bash の例です。リポジトリのフォルダから実行します。

```bash
umask 077
workdir=$(mktemp -d)
export ICHIGYO_AI=gpt
export ICHIGYO_AI_DIR="$workdir/ai"
mkdir "$ICHIGYO_AI_DIR"

openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -pass env:ICHIGYO_PASS -in ichigyo_set.enc -out "$workdir/ichigyo_set.zip" &&
python3 -m zipfile -e "$workdir/ichigyo_set.zip" "$workdir"
```

`ICHIGYO_AI` を設定していないときは、従来の Claude CLI が呼ばれます。

## 2. 依頼を渡して応答を読み込む

1. 個別処理を実行します。GPTの応答が必要になると、処理が止まり、作業フォルダ内の `.request.json` の名前が表示されます。
2. 執筆・文章処理の依頼は親のGPTが処理します。採点・事実読み・強調語選びは、親が必要な文章と判定基準だけを取り出し、コマンド、作業フォルダ、環境変数へのアクセスがない別の係に渡します。外部ページの取得は親が行い、検索には検索語、ページを開く操作には公開URLだけを検索の道具に渡します。事実読みの係には取得した文章と基準を渡します。
3. 親が返答を確認し、同じ識別子の `.response.txt` に、依頼の形式どおりの返答を UTF-8 で保存します。保存先は `ICHIGYO_AI_DIR` です。依頼ファイルの拡張部分 `.request.json` を `.response.txt` に置き換えると、応答のファイル名になります。
4. 同じ入力と引数で同じ個別処理を再実行します。別の依頼が表示されたら繰り返します。検索の応答は URL・見出し・要約・関連語、採点は7項目の点と理由、強調は変更段落のIDとHTMLを指示された形式で返します。公式URLは公開ページを開けたものだけを返し、確認できない候補は `null` にします。

入出力の確認には既存のローカル原稿を使えます。例えば、展開先の `wp_auto/scripts/strict_score.py` にローカルのHTMLのパスと `--keyword` を渡すと、採点を依頼し、再実行時に7項目を合計して表示します。この操作に WordPress の設定は不要です。

## 3. WordPress に接続する場合

WordPress の接続情報は親側の実行環境だけに `WP_SITE`、`WP_USER`、`WP_APP_PASSWORD` として設定します。接続確認は、ログイン中の利用者情報を読み取る操作から始めてください。依頼・応答ファイルには原稿や調査内容が入るため、作業フォルダ内だけで扱います。
