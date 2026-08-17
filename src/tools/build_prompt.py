from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = PROJECT_DIR / "assets" / "prompt_template-aws.md"
SCHEMA_PATH = PROJECT_DIR / "assets" / "episode.schema.json"


def main() -> int:
    print("AWSサービス名を入力してください: ", end="", file=sys.stderr, flush=True)
    try:
        service = input().strip()
    except EOFError:
        print("ERROR: AWSサービス名を入力してください。", file=sys.stderr)
        return 1

    if not service:
        print("ERROR: AWSサービス名を入力してください。", file=sys.stderr)
        return 1

    try:
        prompt = TEMPLATE_PATH.read_text(encoding="utf-8")
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    sys.stdout.write(
        prompt.replace("{{AWS_SERVICE}}", service).replace("{{EPISODE_SCHEMA}}", schema)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
