from __future__ import annotations

import re
import unittest

from typer.testing import CliRunner

from subbake import __version__
from subbake.app import app


class CLITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_root_help_mentions_main_commands(self) -> None:
        result = self.runner.invoke(app, ["--help"])
        output = self._strip_ansi(result.stdout)

        self.assertEqual(result.exit_code, 0)
        self.assertIn("LLM subtitle translation CLI with Chinese as the default target language.", output)
        self.assertIn("Common commands:", output)
        self.assertIn("sbake translate input.srt", output)
        self.assertIn("--provider", output)
        self.assertIn("sbake check-key", output)
        self.assertIn("sbake clean input.srt", output)

    def test_version_flag_prints_package_version(self) -> None:
        result = self.runner.invoke(app, ["-V"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn(f"subbake {__version__}", result.stdout)

    def _strip_ansi(self, value: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", value)
