import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src.cli import parse_args


class CliTests(unittest.TestCase):
    def test_pls_option_can_be_repeated(self) -> None:
        with patch.object(sys, "argv", ["podcast", "episode.json", "--pls", "one.pls", "--pls", "two.pls"]):
            args = parse_args()

        self.assertEqual([Path("one.pls"), Path("two.pls")], args.pls)
