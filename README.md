# Podcast maker

```bash
uv run podcast episodes/episode_00.json --output output
uv run test
uv run python -m pdb -m cli episodes/episode_00.json
```

Create `.env` from `.env.example` and set AWS credentials.

## Configuration

Edit `config.toml` to change shared Polly voices, speech rates, and pause durations for every episode.
Set `audio.backgroundMusic` there, or override it for one run with `--bgm path/to/music.mp3`.

Each episode is written to `output/<episode-json-stem>/`: the final MP3, section MP3s,
and an episode-local `.work/` directory containing Polly sentence audio, the episode-specific
introduction guide, and cache hashes. Guide text comes from `audio.guides` in `config.toml`.
`output/.work/` stores reusable silence, foreground-audio, and shared-guide caches.

## Requirements

`ffmpeg` must be available on `PATH` to build the final MP3.

## License

- This repository contains background music and sound effects files. Please read the license information carefully before using them.:
  - BGM: [`assets/bgm.mp3`](assets/bgm.mp3):  "[Kuru kuru world written by 蒲鉾さちこ](https://dova-s.jp/bgm/detail/23745)".
  - Jingle: [`assets/jingle.mp3`](assets/jingle.mp3): "[文字・テロップ表示音 written by ひふみセオリー](https://dova-s.jp/se/detail/665)".
