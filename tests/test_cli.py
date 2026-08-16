import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src import cli
from src.cli import parse_args


class CliTests(unittest.TestCase):
    def test_pls_option_can_be_repeated(self) -> None:
        with patch.object(sys, "argv", ["podcast", "episode.json", "--pls", "one.pls", "--pls", "two.pls"]):
            args = parse_args()

        self.assertEqual([Path("one.pls"), Path("two.pls")], args.pls)

    def test_bgm_option_overrides_the_settings_file(self) -> None:
        with patch.object(sys, "argv", ["podcast", "episode.json", "--bgm", "custom.mp3"]):
            args = parse_args()

        self.assertEqual(Path("custom.mp3"), args.bgm)

    def test_main_places_episode_files_below_the_output_root(self) -> None:
        args = type(
            "Args",
            (),
            {
                "input": Path("episodes/example.json"),
                "output": Path("output"),
                "pls": [],
                "force": False,
                "bgm": Path("music.mp3"),
                "final_name": None,
            },
        )()
        episode = {"audio": {}}
        with (
            patch.object(cli, "parse_args", return_value=args),
            patch.object(cli, "load_environment"),
            patch.object(cli, "load_episode", return_value=episode),
            patch.object(cli, "load_settings", return_value={"audio": {}}),
            patch.object(cli, "generate_dialogue_audio", return_value={}) as generate,
            patch.object(cli, "build_final_audio") as build,
        ):
            self.assertEqual(0, cli.main())

        self.assertEqual(Path("output/example/.work"), generate.call_args.args[1])
        self.assertEqual(Path("output/.work"), generate.call_args.kwargs["shared_work_dir"])
        self.assertEqual(Path("output/example"), build.call_args.args[1])
        self.assertEqual(Path("output/example/example.mp3"), build.call_args.args[2])
        self.assertEqual(Path("output/.work"), build.call_args.kwargs["shared_work_dir"])
        self.assertEqual({}, build.call_args.kwargs["guide_paths"])
