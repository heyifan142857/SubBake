from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from subbake.checker import validate_full_alignment, validate_translation_batch
from subbake.entities import (
    BatchTranslationResult,
    PipelineOptions,
    PipelineResult,
    ReviewResult,
    SubtitleDocument,
    SubtitleSegment,
    TranslationLine,
    Usage,
)
from subbake.memory import ContextMemory
from subbake.models.base_model import LLMBackend, parse_glossary_entries, parse_translation_lines
from subbake.parsers import load_document, render_document
from subbake.prompts import build_review_messages, build_translation_messages
from subbake.ui import Dashboard


@dataclass(slots=True)
class BatchSlices:
    source: list[SubtitleSegment]
    translated: list[SubtitleSegment]


class SubtitlePipeline:
    def __init__(self, backend: LLMBackend, options: PipelineOptions, dashboard: Dashboard | None = None) -> None:
        self.backend = backend
        self.options = options
        self.memory = ContextMemory()
        self.dashboard = dashboard or Dashboard()

    def run(self) -> PipelineResult:
        input_path = self.options.input_path
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        if self.options.batch_size <= 0:
            raise ValueError("Batch size must be greater than zero.")

        with self.dashboard.running():
            self.dashboard.mark_running("LOAD_FILE")
            self._validate_input_path(input_path)
            self.dashboard.mark_done("LOAD_FILE")

            self.dashboard.mark_running("PARSE")
            document = load_document(input_path)
            translation_batches = self._chunk_segments(document.segments)
            review_batches = len(translation_batches) if self.options.final_review else 0
            total_steps = 2 + len(translation_batches) + 1 + review_batches + 1
            self.dashboard.set_total_steps(total_steps)
            self.dashboard.mark_done("PARSE")

            translated_segments = self._translate_document(document, translation_batches)

            self.dashboard.mark_running("VALIDATE")
            validate_full_alignment(document.segments, translated_segments)
            self.dashboard.mark_done("VALIDATE")

            reviewed_segments = translated_segments
            if self.options.final_review and translated_segments:
                reviewed_segments = self._review_document(document, translated_segments)
                validate_full_alignment(document.segments, reviewed_segments)

            output_segments = self._build_output_segments(document, reviewed_segments)
            output_path = self._resolve_output_path(input_path)
            self.dashboard.mark_running("WRITE_OUTPUT")
            rendered = render_document(document, output_segments, bilingual=self.options.bilingual)
            output_path.write_text(rendered, encoding="utf-8")
            self.dashboard.mark_done("WRITE_OUTPUT")
            self.dashboard.clear_batch()

        return PipelineResult(
            output_path=output_path,
            batches_translated=len(translation_batches),
            review_batches=len(translation_batches) if self.options.final_review else 0,
            usage=self.dashboard.usage,
        )

    def _translate_document(
        self,
        document: SubtitleDocument,
        translation_batches: list[list[SubtitleSegment]],
    ) -> list[SubtitleSegment]:
        translated_segments: list[SubtitleSegment] = []
        total_batches = len(translation_batches)
        for batch_index, batch_segments in enumerate(translation_batches, start=1):
            label = f"TRANSLATE_BATCH {batch_index}/{total_batches}"
            self.dashboard.mark_running("TRANSLATE_BATCH", label=label)
            started_at = perf_counter()
            batch_result, usage = self._translate_batch_with_retry(batch_segments)
            latency = perf_counter() - started_at
            self.dashboard.set_batch(batch_index, total_batches, latency, label)
            self.dashboard.add_usage(usage)
            self.memory.update(batch_result.summary, batch_result.glossary_updates)
            translated_segments.extend(
                self._materialize_translations(batch_segments, batch_result.lines)
            )
            self.dashboard.mark_done("TRANSLATE_BATCH")
        return translated_segments

    def _review_document(
        self,
        document: SubtitleDocument,
        translated_segments: list[SubtitleSegment],
    ) -> list[SubtitleSegment]:
        reviewed_segments: list[SubtitleSegment] = []
        slices = self._zip_batches(document.segments, translated_segments)
        total_batches = len(slices)
        for batch_index, batch in enumerate(slices, start=1):
            label = f"FINAL_REVIEW {batch_index}/{total_batches}"
            self.dashboard.mark_running("FINAL_REVIEW", label=label)
            started_at = perf_counter()
            review_result, usage = self._review_batch_with_retry(batch.source, batch.translated)
            latency = perf_counter() - started_at
            self.dashboard.set_batch(batch_index, total_batches, latency, label)
            self.dashboard.add_usage(usage)
            reviewed_segments.extend(
                self._materialize_translations(batch.source, review_result.lines)
            )
            self.dashboard.mark_done("FINAL_REVIEW")
        return reviewed_segments

    def _translate_batch_with_retry(
        self,
        batch_segments: list[SubtitleSegment],
    ) -> tuple[BatchTranslationResult, Usage]:
        attempts = self.options.retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                messages = build_translation_messages(
                    batch_segments=batch_segments,
                    memory=self.memory,
                    source_language=self.options.source_language,
                    target_language=self.options.target_language,
                )
                if last_error is not None:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "The previous response failed validation.\n"
                                f"Validation error: {last_error}\n"
                                "Re-send corrected JSON only."
                            ),
                        }
                    )
                payload, usage = self.backend.generate_json(messages)
                lines = parse_translation_lines(payload.get("lines", []))
                validate_translation_batch(batch_segments, lines)
                glossary_updates = parse_glossary_entries(payload.get("glossary_updates", []))
                result = BatchTranslationResult(
                    lines=lines,
                    summary=str(payload.get("summary", "")).strip(),
                    glossary_updates=glossary_updates,
                )
                return result, usage
            except Exception as exc:
                last_error = exc
                if attempt == attempts:
                    raise RuntimeError(
                        f"Translation batch failed after {attempts} attempts."
                    ) from exc
        raise RuntimeError("Translation batch retry loop ended unexpectedly.")

    def _review_batch_with_retry(
        self,
        source_segments: list[SubtitleSegment],
        translated_segments: list[SubtitleSegment],
    ) -> tuple[ReviewResult, Usage]:
        attempts = self.options.retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                messages = build_review_messages(
                    source_segments=source_segments,
                    translated_segments=translated_segments,
                    memory=self.memory,
                    target_language=self.options.target_language,
                )
                if last_error is not None:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "The previous review response failed validation.\n"
                                f"Validation error: {last_error}\n"
                                "Re-send corrected JSON only."
                            ),
                        }
                    )
                payload, usage = self.backend.generate_json(messages)
                lines = parse_translation_lines(payload.get("lines", []))
                validate_translation_batch(source_segments, lines)
                result = ReviewResult(
                    lines=lines,
                    review_notes=str(payload.get("review_notes", "")).strip(),
                )
                return result, usage
            except Exception as exc:
                last_error = exc
                if attempt == attempts:
                    raise RuntimeError(
                        f"Final review batch failed after {attempts} attempts."
                    ) from exc
        raise RuntimeError("Review batch retry loop ended unexpectedly.")

    def _build_output_segments(
        self,
        document: SubtitleDocument,
        translated_segments: list[SubtitleSegment],
    ) -> list[SubtitleSegment]:
        if document.format not in {"srt", "vtt"} or not self.options.bilingual:
            return translated_segments

        bilingual_segments: list[SubtitleSegment] = []
        for source, translated in zip(document.segments, translated_segments, strict=True):
            bilingual_segments.append(
                SubtitleSegment(
                    id=translated.id,
                    start=translated.start,
                    end=translated.end,
                    identifier=translated.identifier,
                    settings=translated.settings,
                    text="\n".join(part for part in [source.text, translated.text] if part != ""),
                )
            )
        return bilingual_segments

    def _materialize_translations(
        self,
        source_segments: list[SubtitleSegment],
        lines: list[TranslationLine],
    ) -> list[SubtitleSegment]:
        rendered: list[SubtitleSegment] = []
        for source, line in zip(source_segments, lines, strict=True):
            rendered.append(
                SubtitleSegment(
                    id=source.id,
                    start=source.start,
                    end=source.end,
                    identifier=source.identifier,
                    settings=source.settings,
                    text=line.translation,
                )
            )
        return rendered

    def _chunk_segments(self, segments: list[SubtitleSegment]) -> list[list[SubtitleSegment]]:
        if not segments:
            return []
        size = self.options.batch_size
        return [segments[index : index + size] for index in range(0, len(segments), size)]

    def _zip_batches(
        self,
        source_segments: list[SubtitleSegment],
        translated_segments: list[SubtitleSegment],
    ) -> list[BatchSlices]:
        size = self.options.batch_size
        batches: list[BatchSlices] = []
        for index in range(0, len(source_segments), size):
            batches.append(
                BatchSlices(
                    source=source_segments[index : index + size],
                    translated=translated_segments[index : index + size],
                )
            )
        return batches

    def _resolve_output_path(self, input_path: Path) -> Path:
        if self.options.output_path is not None:
            return self.options.output_path
        suffix = input_path.suffix.lower()
        flavor = "bilingual" if self.options.bilingual else "translated"
        return input_path.with_name(f"{input_path.stem}.{flavor}{suffix}")

    def _validate_input_path(self, input_path: Path) -> None:
        supported = {".srt", ".vtt", ".txt"}
        if input_path.suffix.lower() not in supported:
            raise ValueError("Supported input formats are .srt, .vtt, and .txt.")
