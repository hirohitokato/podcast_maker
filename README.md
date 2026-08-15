# Podcast maker

```bash
uv run podcast episodes/episode_00.json --output output/episode_00
uv run test
uv run python -m pdb -m cli episodes/episode_00.json
```

Create `.env` from `.env.example` and set AWS credentials.

## Configuration

Edit `settings.jsonc` to change shared Polly voices, speech rates, and pause durations for every episode.

## Requirements

`ffmpeg` must be available on `PATH` to build the final MP3.
