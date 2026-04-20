from __future__ import annotations

import unittest

from typer.testing import CliRunner

from subbake import __version__
from subbake.app import app


class CLITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_root_help_mentions_main_commands(self) -> None:
        result = self.runner.invoke(app, ["--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("sbake translate input.srt --provider openai", result.stdout)
        self.assertIn("sbake check-key --provider openai", result.stdout)
        self.assertIn("sbake clean input.srt", result.stdout)

    def test_version_flag_prints_package_version(self) -> None:
        result = self.runner.invoke(app, ["-V"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn(f"subbake {__version__}", result.stdout)
