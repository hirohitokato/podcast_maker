# Podcast maker

```bash
uv run podcast episodes/episode_00.json --output output/episode_00
uv run test
uv run python -m pdb -m cli episodes/episode_00.json
```

Create `.env` from `.env.example` and set AWS credentials.

## Configuration

Edit `settings.jsonc` to change shared Polly voices, speech rates, and pause durations for every episode.
Set `audio.backgroundMusic` there, or override it for one run with `--bgm path/to/music.mp3`.

## Requirements

`ffmpeg` must be available on `PATH` to build the final MP3.

## License

- The file([`assets/Kuru_Kuru_world.mp3`](assets/Kuru_Kuru_world.mp3)) is downloaded from "[Kuru kuru world written by 蒲鉾さちこ](https://dova-s.jp/bgm/detail/23745)".
