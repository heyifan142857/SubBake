from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from subbake.entities import PipelineOptions, Usage
from subbake.models import build_backend
from subbake.pipeline import SubtitlePipeline


class QuietDashboard:
    def __init__(self) -> None:
        self.usage = Usage()
        self.total_steps = 0
        self.completed_steps = 0

    @contextmanager
    def running(self):
        yield self

    def set_total_steps(self, total_steps: int) -> None:
        self.total_steps = total_steps

    def mark_running(self, stage: str, label: str | None = None) -> None:
        _ = (stage, label)

    def mark_done(self, stage: str, advance: bool = True) -> None:
        _ = stage
        if advance:
            self.completed_steps += 1

    def add_usage(self, usage: Usage) -> None:
        self.usage.add(usage)

    def restore_usage(self, usage: Usage) -> None:
        self.usage = Usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
        )

    def restore_progress(self, completed_steps: int) -> None:
        self.completed_steps = completed_steps

    def set_batch(self, index: int, total: int, latency_seconds: float, stage_label: str) -> None:
        _ = (index, total, latency_seconds, stage_label)

    def clear_batch(self) -> None:
        return


class PipelineTestCase(unittest.TestCase):
    def test_dry_run_returns_batch_plan_without_writing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "sample.txt"
            input_path.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")

            options = PipelineOptions(
                input_path=input_path,
                batch_size=2,
                dry_run=True,
                work_dir=temp_path / "runtime",
            )
            pipeline = SubtitlePipeline(
                backend=None,
                options=options,
                dashboard=QuietDashboard(),
            )

            result = pipeline.run()

            self.assertTrue(result.dry_run)
            self.assertEqual(
                [(entry.index, entry.size, entry.first_id, entry.last_id) for entry in result.planned_batches],
                [(1, 2, "1", "2"), (2, 2, "3", "4"), (3, 1, "5", "5")],
            )
            self.assertIsNone(result.output_path)
            self.assertFalse((temp_path / "sample.translated.txt").exists())
            self.assertFalse(result.state_path.exists())

    def test_mock_translation_writes_output_and_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "episode.txt"
            input_path.write_text("Hello Alice.\nDamn it.\nMove.\n", encoding="utf-8")

            options = PipelineOptions(
                input_path=input_path,
                provider="mock",
                model="mock-zh",
                batch_size=2,
                final_review=True,
                work_dir=temp_path / "runtime",
            )
            pipeline = SubtitlePipeline(
                backend=build_backend("mock", "mock-zh"),
                options=options,
                dashboard=QuietDashboard(),
            )

            result = pipeline.run()

            self.assertEqual(result.batches_translated, 2)
            self.assertEqual(result.review_batches, 2)
            self.assertTrue(result.output_path.exists())
            self.assertTrue(result.state_path.exists())
            self.assertTrue(result.glossary_path.exists())
            self.assertGreater(result.usage.total_tokens, 0)

            output_text = result.output_path.read_text(encoding="utf-8")
            self.assertIn("[MOCK-ZH] Hello Alice.", output_text)
            self.assertIn("[MOCK-ZH] Damn it.", output_text)

            glossary = json.loads(result.glossary_path.read_text(encoding="utf-8"))
            self.assertEqual(glossary["Alice"], "Alice")

            state = json.loads(result.state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["translation_batches_completed"], 2)
            self.assertEqual(state["review_batches_completed"], 2)
