from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from subbake import __version__
from subbake.app import app
from subbake.storage import build_runtime_paths


class CLITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_root_help_mentions_main_commands(self) -> None:
        result = self.runner.invoke(app, ["--help"])
        output = self._strip_ansi(result.stdout)

        self.assertEqual(result.exit_code, 0)
        self.assertIn("LLM subtitle translation CLI with Chinese as the default target language", output)
        self.assertIn("another target such as en / ja / fr.", output)
        self.assertIn("Common commands:", output)
        self.assertIn("sbake translate input.srt", output)
        self.assertIn("--provider", output)
        self.assertIn("--fast", output)
        self.assertIn("--target-language", output)
        self.assertIn("--config", output)
        self.assertIn("--profile", output)
        self.assertIn("sbake check-key", output)
        self.assertIn("sbake clean input.srt", output)

    def test_version_flag_prints_package_version(self) -> None:
        result = self.runner.invoke(app, ["-V"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn(f"subbake {__version__}", result.stdout)

    def test_clean_file_target_removes_only_runs_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "episode.srt"
            input_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello\n", encoding="utf-8")
            runtime = build_runtime_paths(input_path)
            runtime.run_dir.mkdir(parents=True, exist_ok=True)
            runtime.cache_dir.mkdir(parents=True, exist_ok=True)
            runtime.glossary_path.parent.mkdir(parents=True, exist_ok=True)
            (runtime.run_dir / "run_state.json").write_text("{}", encoding="utf-8")
            (runtime.cache_dir / "sample.json").write_text("{}", encoding="utf-8")
            runtime.glossary_path.write_text("{}", encoding="utf-8")

            result = self.runner.invoke(app, ["clean", str(input_path)])

            self.assertEqual(result.exit_code, 0)
            self.assertFalse(runtime.run_dir.exists())
            self.assertTrue(runtime.cache_dir.exists())
            self.assertTrue(runtime.glossary_path.exists())

    def test_clean_directory_target_removes_all_runtime_artifacts_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            project_dir = temp_path / "project"
            runtime_root = project_dir / ".subbake"
            (runtime_root / "runs").mkdir(parents=True, exist_ok=True)
            (runtime_root / "cache").mkdir(parents=True, exist_ok=True)
            (runtime_root / "glossary.json").write_text("{}", encoding="utf-8")

            result = self.runner.invoke(app, ["clean", str(project_dir)])

            self.assertEqual(result.exit_code, 0)
            self.assertFalse(runtime_root.exists())

    def test_translate_uses_auto_discovered_config_profile(self) -> None:
        with self.runner.isolated_filesystem():
            Path("subbake.toml").write_text(
                'default_profile = "mock_en"\n\n'
                "[defaults]\n"
                "final_review = false\n"
                "resume = false\n"
                "cache = false\n\n"
                "[profiles.mock_en]\n"
                'provider = "mock"\n'
                'model = "mock-zh"\n'
                'target_language = "en"\n',
                encoding="utf-8",
            )
            Path("clip.txt").write_text("hello\n", encoding="utf-8")

            result = self.runner.invoke(app, ["translate", "clip.txt"])

            self.assertEqual(result.exit_code, 0)
            self.assertIn("[MOCK-EN] hello", Path("clip.translated.txt").read_text(encoding="utf-8"))
            output = self._strip_ansi(result.stdout)
            self.assertIn("Config:", output)
            self.assertIn("profile mock_en", output)

    def test_translate_command_line_overrides_config_values(self) -> None:
        with self.runner.isolated_filesystem():
            Path("subbake.toml").write_text(
                'default_profile = "mock_en"\n\n'
                "[profiles.mock_en]\n"
                'provider = "mock"\n'
                'model = "mock-zh"\n'
                'target_language = "en"\n'
                "final_review = false\n",
                encoding="utf-8",
            )
            Path("clip.txt").write_text("hello\n", encoding="utf-8")

            result = self.runner.invoke(
                app,
                ["translate", "clip.txt", "--target-language", "zh"],
            )

            self.assertEqual(result.exit_code, 0)
            self.assertIn("[MOCK-ZH] hello", Path("clip.translated.txt").read_text(encoding="utf-8"))

    def test_translate_requires_default_profile_when_multiple_profiles_exist(self) -> None:
        with self.runner.isolated_filesystem():
            Path("subbake.toml").write_text(
                "[profiles.mock_en]\n"
                'provider = "mock"\n'
                'model = "mock-zh"\n'
                'target_language = "en"\n\n'
                "[profiles.mock_zh]\n"
                'provider = "mock"\n'
                'model = "mock-zh"\n'
                'target_language = "zh"\n',
                encoding="utf-8",
            )
            Path("clip.txt").write_text("hello\n", encoding="utf-8")

            result = self.runner.invoke(app, ["translate", "clip.txt"])
            output = self._strip_ansi(result.stdout)

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Multiple config profiles are defined", output)
            self.assertIn("--profile", output)

    def test_translate_profile_option_selects_named_profile(self) -> None:
        with self.runner.isolated_filesystem():
            Path("subbake.toml").write_text(
                "[profiles.mock_en]\n"
                'provider = "mock"\n'
                'model = "mock-zh"\n'
                'target_language = "en"\n'
                "final_review = false\n\n"
                "[profiles.mock_zh]\n"
                'provider = "mock"\n'
                'model = "mock-zh"\n'
                'target_language = "zh"\n'
                "final_review = false\n",
                encoding="utf-8",
            )
            Path("clip.txt").write_text("hello\n", encoding="utf-8")

            result = self.runner.invoke(
                app,
                ["translate", "clip.txt", "--profile", "mock_zh"],
            )

            self.assertEqual(result.exit_code, 0)
            self.assertIn("[MOCK-ZH] hello", Path("clip.translated.txt").read_text(encoding="utf-8"))

    def _strip_ansi(self, value: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", value)
