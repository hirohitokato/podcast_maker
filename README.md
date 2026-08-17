# Podcast Maker

Amazon Pollyで、AWSを題材にした英会話学習用MP3を作成するツールです。台本JSONから通常速度、日英交互、遅速、シャドーイングの各パートとガイド音声を作り、BGMとジングルを加えた1本のMP3にまとめます。

## 出力サンプル

[sampleディレクトリ](./sample/)のjsonファイル、mp3ファイルを参照してください。

## 動作環境

- Python 3.14以上と[uv](https://docs.astral.sh/uv/)
- `ffmpeg`（`PATH`上にあること）
- Amazon Pollyを利用できるAWS認証情報

## セットアップ

```bash
uv sync
cp .env.example .env
```

`.env`にAWS認証情報とリージョンを設定します。

```dotenv
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=ap-northeast-1
```

## 使い方（台本作成～MP3作成）

大まかな流れは次のとおりです。

1. 台本JSONを作成する
2. 台本JSONを指定してMP3を作成する

### 1.台本JSONを作成

JSONファイルに会話の台本を記述します。スキーマとサンプルは以下です。

- 台本JSONのスキーマ: [./assets/episode.schema.json](./assets/episode.schema.json)
- サンプル: [sample/sample.json](./sample/sample.json)

これをすべて人間が書くのは大変なので、生成AIに台本の叩き台を作成させることをおすすめします。
`uv run build_prompt`を使うと、入力したAWSサービスを題材にした台本生成用のプロンプトを作成できます。

```bash
$ uv run build_prompt
AWSサービス名を入力してください: <Lambdaなどのサービス名を入力してEnter>

あなたは、AWSに詳しいテクニカルライター兼、英語学習者向けポッドキャストの脚本家です。

指定されたAWSサービスについて、
「自然な英会話を楽しみながら、AWSサービスの機能と使いどころを理解できる」
短いポッドキャスト台本を作成してください。
...
```

このプロンプトをChatGPTなどにコピー＆ペーストするだけで、台本JSONを生成してくれます。あとは内容を確認してブラッシュアップしてください。

### 2.台本JSONからMP3ファイルを作成

1で作成した、台本の書かれたJSONファイルを使ってMP3を作成します。

```bash
# sample/sample.json で作成する場合
$ uv run make sample/sample.json --output output
[1/3] Generating dialogue and guide audio
AWS credentials verified
  Account: XXXXXXXXXXXXX
  ARN:     arn:aws:...

Registering Polly lexicon: ...

[001/069] GENERATED EN woman    001_woman_en_normal.mp3
...
[3/3] Mixing background music
Final audio created
-------------------
Section 1 : output/sample/section_01_en_normal.mp3
Section 2 : output/sample/section_02_en_ja.mp3
Section 3 : output/sample/section_03_en_slow.mp3
Section 4 : output/sample/section_04_en_shadowing.mp3
Final MP3 : output/sample/sample.mp3
```

MP3ファイルは`-o`オプションで指定したフォルダにに作成されます。同じディレクトリには通常速度・日英交互・遅速・シャドーイングの各セクションMP3も出力されます。

## 動作設定

共有設定は`config.toml`で変更します。Pollyの声と速度、ポーズ、BGM、会話・SEの音量、アルバム名・作成者、ガイド文を設定できます。

台本JSONには少なくとも`title`、`abstract`（`en`・`ja`で各100〜150文字程度の紹介文）、`english_learning.keywords`、`dialogue`を記述します。これらは音声内容と最終MP3のメタデータに使われます。MP3のTIT3タグには`abstract.ja`を設定します。


## License

- [AGPL-3.0 License](./LICENSE)
- BGM: [`assets/bgm.mp3`](assets/bgm.mp3) — [Kuru kuru world / 蒲鉾さちこ](https://dova-s.jp/bgm/detail/23745)
- Jingle: [`assets/jingle.mp3`](assets/jingle.mp3) — [文字・テロップ表示音 / ひふみセオリー](https://dova-s.jp/se/detail/665)
