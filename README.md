# Podcast Maker

Amazon Pollyで、AWSを題材にした英会話学習用MP3を作成するツールです。台本JSONから通常速度、日英交互、遅速、シャドーイングの各パートとガイド音声を作り、BGMとジングルを加えた1本のMP3にまとめます。

## 必要なもの

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

## 使い方

台本JSONを指定して実行します。

```bash
uv run podcast episodes/episode_00.json --output output
```

最終MP3は`output/episode_00/episode_00.mp3`に作成されます。同じディレクトリには通常速度・日英交互・遅速・シャドーイングの各セクションMP3も出力されます。

`--bgm path/to/music.mp3`で、その実行だけBGMを差し替えられます。`--force`はPolly音声キャッシュを無視して再生成します。

## 設定と台本

共有設定は`config.toml`で変更します。Pollyの声と速度、ポーズ、BGM、会話・SEの音量、アルバム名・作成者、ガイド文を設定できます。

台本JSONには少なくとも`title`、`scene`、`aws_services`、`dialogue`を記述します。これらは音声内容と最終MP3のメタデータに使われます。

## テスト

```bash
uv run test
```

## License

- [AGPL-3.0 License](./LICENSE)
- BGM: [`assets/bgm.mp3`](assets/bgm.mp3) — [Kuru kuru world / 蒲鉾さちこ](https://dova-s.jp/bgm/detail/23745)
- Jingle: [`assets/jingle.mp3`](assets/jingle.mp3) — [文字・テロップ表示音 / ひふみセオリー](https://dova-s.jp/se/detail/665)
