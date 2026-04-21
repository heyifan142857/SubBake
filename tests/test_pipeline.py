from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from subbake.entities import PipelineOptions, Usage
from subbake.models import build_backend
from subbake.models.base_model import LLMBackend
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


class ScriptedBackend(LLMBackend):
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.call_count = 0

    def generate_json(self, messages: list[dict[str, str]]) -> tuple[dict, Usage]:
        self.call_count += 1
        if self.fail_on_call is not None and self.call_count == self.fail_on_call:
            raise RuntimeError("Injected backend failure.")

        prompt = "\n".join(message["content"] for message in messages)
        batch_payload = json.loads(self._extract_between(prompt, "BATCH_JSON_START", "BATCH_JSON_END"))
        return (
            {
                "lines": [
                    {
                        "id": item["id"],
                        "translation": "" if not item["text"].strip() else f"[SCRIPTED] {item['text']}",
                    }
                    for item in batch_payload["lines"]
                ],
                "summary": f"batch-{self.call_count}",
                "glossary_updates": [],
            },
            Usage(input_tokens=10, output_tokens=10, total_tokens=20),
        )

    def check_credentials(self) -> tuple[bool, str]:
        return True, "ok"

    def _extract_between(self, text: str, start_marker: str, end_marker: str) -> str:
        start_index = text.index(start_marker) + len(start_marker)
        end_index = text.index(end_marker, start_index)
        return text[start_index:end_index].strip()


class FailingBackend(LLMBackend):
    def generate_json(self, messages: list[dict[str, str]]) -> tuple[dict, Usage]:
        raise AssertionError("Backend should not be called.")

    def check_credentials(self) -> tuple[bool, str]:
        return True, "ok"


class StructuralFailureBackend(LLMBackend):
    def __init__(self) -> None:
        self.call_sizes: list[int] = []

    def generate_json(self, messages: list[dict[str, str]]) -> tuple[dict, Usage]:
        prompt = "\n".join(message["content"] for message in messages)
        batch_payload = json.loads(self._extract_between(prompt, "BATCH_JSON_START", "BATCH_JSON_END"))
        lines = batch_payload["lines"]
        batch_size = len(lines)
        self.call_sizes.append(batch_size)

        if batch_size >= 4:
            return (
                {
                    "lines": [
                        {"id": item["id"], "translation": f"[SPLIT] {item['text']}"}
                        for item in lines[:-1]
                    ],
                    "summary": f"invalid-count-{batch_size}",
                    "glossary_updates": [],
                },
                Usage(input_tokens=5, output_tokens=5, total_tokens=10),
            )
        if batch_size >= 2:
            return (
                {
                    "lines": [
                        {
                            "id": item["id"],
                            "translation": "" if index == 0 else f"[SPLIT] {item['text']}",
                        }
                        for index, item in enumerate(lines)
                    ],
                    "summary": f"invalid-empty-{batch_size}",
                    "glossary_updates": [],
                },
                Usage(input_tokens=5, output_tokens=5, total_tokens=10),
            )
        return (
            {
                "lines": [
                    {"id": item["id"], "translation": f"[SPLIT] {item['text']}"}
                    for item in lines
                ],
                "summary": f"ok-{batch_size}",
                "glossary_updates": [],
            },
            Usage(input_tokens=5, output_tokens=5, total_tokens=10),
        )

    def check_credentials(self) -> tuple[bool, str]:
        return True, "ok"

    def _extract_between(self, text: str, start_marker: str, end_marker: str) -> str:
        start_index = text.index(start_marker) + len(start_marker)
        end_index = text.index(end_marker, start_index)
        return text[start_index:end_index].strip()


class AlwaysMissingLineBackend(LLMBackend):
    def generate_json(self, messages: list[dict[str, str]]) -> tuple[dict, Usage]:
        prompt = "\n".join(message["content"] for message in messages)
        batch_payload = json.loads(self._extract_between(prompt, "BATCH_JSON_START", "BATCH_JSON_END"))
        lines = batch_payload["lines"]
        return (
            {
                "lines": [
                    {"id": item["id"], "translation": f"[BROKEN] {item['text']}"}
                    for item in lines[:-1]
                ],
                "summary": "broken",
                "glossary_updates": [],
            },
            Usage(input_tokens=5, output_tokens=5, total_tokens=10),
        )

    def check_credentials(self) -> tuple[bool, str]:
        return True, "ok"

    def _extract_between(self, text: str, start_marker: str, end_marker: str) -> str:
        start_index = text.index(start_marker) + len(start_marker)
        end_index = text.index(end_marker, start_index)
        return text[start_index:end_index].strip()


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
            self.assertEqual(result.review_batches, 1)
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
            self.assertEqual(state["review_batches_completed"], 1)
            self.assertTrue(state["validation_completed"])
            self.assertNotIn("translated_segments", state)
            self.assertNotIn("reviewed_segments", state)

            translated_shards = sorted(result.state_path.parent.joinpath("translated_batches").glob("*.json"))
            reviewed_shards = sorted(result.state_path.parent.joinpath("reviewed_batches").glob("*.json"))
            self.assertEqual(len(translated_shards), 2)
            self.assertEqual(len(reviewed_shards), 1)

    def test_resume_restores_from_incremental_batch_shards(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "resume.txt"
            input_path.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
            work_dir = temp_path / "runtime"

            first_pipeline = SubtitlePipeline(
                backend=ScriptedBackend(fail_on_call=2),
                options=PipelineOptions(
                    input_path=input_path,
                    batch_size=2,
                    final_review=False,
                    retries=0,
                    work_dir=work_dir,
                ),
                dashboard=QuietDashboard(),
            )

            with self.assertRaises(RuntimeError):
                first_pipeline.run()

            state_files = list(work_dir.glob("runs/*/run_state.json"))
            self.assertEqual(len(state_files), 1)
            state = json.loads(state_files[0].read_text(encoding="utf-8"))
            self.assertEqual(state["translation_batches_completed"], 1)
            self.assertFalse(state["validation_completed"])

            second_backend = ScriptedBackend()
            second_pipeline = SubtitlePipeline(
                backend=second_backend,
                options=PipelineOptions(
                    input_path=input_path,
                    batch_size=2,
                    final_review=False,
                    retries=0,
                    work_dir=work_dir,
                ),
                dashboard=QuietDashboard(),
            )

            result = second_pipeline.run()

            self.assertEqual(second_backend.call_count, 2)
            self.assertEqual(result.batches_translated, 3)
            self.assertEqual(result.review_batches, 0)
            self.assertEqual(
                result.output_path.read_text(encoding="utf-8"),
                "[SCRIPTED] one\n[SCRIPTED] two\n[SCRIPTED] three\n[SCRIPTED] four\n[SCRIPTED] five\n",
            )
            translated_shards = sorted(result.state_path.parent.joinpath("translated_batches").glob("*.json"))
            self.assertEqual(len(translated_shards), 3)

    def test_smart_batching_splits_large_dialogue_before_hard_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "long.txt"
            input_path.write_text(
                "\n".join([f"{'A' * 140}." for _ in range(15)]) + "\n",
                encoding="utf-8",
            )

            pipeline = SubtitlePipeline(
                backend=None,
                options=PipelineOptions(
                    input_path=input_path,
                    batch_size=50,
                    dry_run=True,
                    work_dir=temp_path / "runtime",
                ),
                dashboard=QuietDashboard(),
            )

            result = pipeline.run()

            self.assertGreater(len(result.planned_batches), 1)
            self.assertLess(max(entry.size for entry in result.planned_batches), 15)

    def test_high_risk_fragment_batching_shrinks_batch_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "fragments.txt"
            input_path.write_text(
                "\n".join(
                    [
                        "i thought",
                        "we could still",
                        "make it out",
                        "before dawn",
                    ]
                    * 5
                )
                + "\n",
                encoding="utf-8",
            )

            pipeline = SubtitlePipeline(
                backend=None,
                options=PipelineOptions(
                    input_path=input_path,
                    batch_size=30,
                    dry_run=True,
                    work_dir=temp_path / "runtime",
                ),
                dashboard=QuietDashboard(),
            )

            result = pipeline.run()

            self.assertGreater(len(result.planned_batches), 1)
            self.assertLessEqual(max(entry.size for entry in result.planned_batches), 9)

    def test_structural_translation_failures_trigger_recursive_split_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "split.txt"
            input_path.write_text("Alpha.\nBravo.\nCharlie.\nDelta.\n", encoding="utf-8")
            backend = StructuralFailureBackend()

            result = SubtitlePipeline(
                backend=backend,
                options=PipelineOptions(
                    input_path=input_path,
                    batch_size=8,
                    final_review=False,
                    retries=0,
                    work_dir=temp_path / "runtime",
                ),
                dashboard=QuietDashboard(),
            ).run()

            self.assertEqual(
                result.output_path.read_text(encoding="utf-8"),
                "[SPLIT] Alpha.\n[SPLIT] Bravo.\n[SPLIT] Charlie.\n[SPLIT] Delta.\n",
            )
            self.assertEqual(backend.call_sizes, [4, 2, 1, 1, 2, 1, 1])

    def test_translation_failure_message_explains_missing_lines_and_smaller_batch_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "broken.txt"
            input_path.write_text("Alpha.\nBravo.\n", encoding="utf-8")

            pipeline = SubtitlePipeline(
                backend=AlwaysMissingLineBackend(),
                options=PipelineOptions(
                    input_path=input_path,
                    batch_size=50,
                    final_review=False,
                    retries=0,
                    work_dir=temp_path / "runtime",
                ),
                dashboard=QuietDashboard(),
            )

            with self.assertRaises(RuntimeError) as context:
                pipeline.run()

            message = str(context.exception)
            self.assertIn("Model output is missing subtitle entries or merged neighboring lines.", message)
            self.assertIn("Try rerunning with a smaller --batch-size", message)
            self.assertIn("--batch-size 25", message)
            self.assertIn("--batch-size 15", message)

    def test_bilingual_render_reuses_existing_translation_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "render.txt"
            input_path.write_text("hello\nworld\n", encoding="utf-8")
            work_dir = temp_path / "runtime"

            first_result = SubtitlePipeline(
                backend=ScriptedBackend(),
                options=PipelineOptions(
                    input_path=input_path,
                    batch_size=2,
                    bilingual=False,
                    final_review=False,
                    work_dir=work_dir,
                ),
                dashboard=QuietDashboard(),
            ).run()

            second_result = SubtitlePipeline(
                backend=FailingBackend(),
                options=PipelineOptions(
                    input_path=input_path,
                    batch_size=2,
                    bilingual=True,
                    final_review=False,
                    work_dir=work_dir,
                ),
                dashboard=QuietDashboard(),
            ).run()

            self.assertEqual(first_result.batches_translated, 1)
            self.assertEqual(second_result.batches_translated, 1)
            self.assertEqual(
                second_result.output_path.read_text(encoding="utf-8"),
                "hello\n[SCRIPTED] hello\nworld\n[SCRIPTED] world\n",
            )

    def test_translation_memory_reuses_lines_across_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            work_dir = temp_path / "runtime"
            first_input = temp_path / "episode1.txt"
            second_input = temp_path / "episode2.txt"
            first_input.write_text("Same line\nAnother line\n", encoding="utf-8")
            second_input.write_text("Same line\nAnother line\n", encoding="utf-8")

            first_backend = ScriptedBackend()
            first_result = SubtitlePipeline(
                backend=first_backend,
                options=PipelineOptions(
                    input_path=first_input,
                    batch_size=2,
                    final_review=False,
                    work_dir=work_dir,
                ),
                dashboard=QuietDashboard(),
            ).run()

            second_backend = FailingBackend()
            second_result = SubtitlePipeline(
                backend=second_backend,
                options=PipelineOptions(
                    input_path=second_input,
                    batch_size=2,
                    final_review=False,
                    work_dir=work_dir,
                ),
                dashboard=QuietDashboard(),
            ).run()

            self.assertEqual(first_backend.call_count, 1)
            self.assertEqual(
                second_result.output_path.read_text(encoding="utf-8"),
                "[SCRIPTED] Same line\n[SCRIPTED] Another line\n",
            )
            tm_path = work_dir / "translation_memory.json"
            tm_data = json.loads(tm_path.read_text(encoding="utf-8"))
            self.assertIn("same line", tm_data)
            self.assertIn("another line", tm_data)
