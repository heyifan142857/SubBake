from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from subbake.checker import validate_full_alignment, validate_translation_batch
from subbake.entities import (
    BatchPlanEntry,
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
from subbake.storage import (
    CacheStore,
    FailureStore,
    GlossaryStore,
    ResumeSnapshot,
    RunStateStore,
    build_pipeline_fingerprint,
    build_request_hash,
    build_runtime_paths,
    compute_input_signature,
)
from subbake.ui import Dashboard


@dataclass(slots=True)
class BatchSlices:
    source: list[SubtitleSegment]
    translated: list[SubtitleSegment]


class SubtitlePipeline:
    def __init__(self, backend: LLMBackend | None, options: PipelineOptions, dashboard: Dashboard | None = None) -> None:
        self.backend = backend
        self.options = options
        self.memory = ContextMemory()
        self.dashboard = dashboard or Dashboard()
        self.cache_hits = 0
        self.runtime_paths = build_runtime_paths(
            input_path=options.input_path,
            work_dir=options.work_dir,
            glossary_path=options.glossary_path,
        )
        self.cache_store = CacheStore(self.runtime_paths.cache_dir)
        self.glossary_store = GlossaryStore(self.runtime_paths.glossary_path)
        self.failure_store = FailureStore(self.runtime_paths.failures_dir)
        self.state_store: RunStateStore | None = None
        self.input_signature: dict | None = None
        self.output_path = self._resolve_output_path(options.input_path)

    def run(self) -> PipelineResult:
        input_path = self.options.input_path
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        if self.options.batch_size <= 0:
            raise ValueError("Batch size must be greater than zero.")

        with self.dashboard.running():
            self.dashboard.mark_running("LOAD_FILE")
            self._validate_input_path(input_path)
            self.input_signature = compute_input_signature(input_path)
            self.state_store = RunStateStore(
                path=self.runtime_paths.state_path,
                pipeline_fingerprint=build_pipeline_fingerprint(self.options, self.input_signature),
            )
            self.dashboard.mark_done("LOAD_FILE")

            self.dashboard.mark_running("PARSE")
            document = load_document(input_path)
            translation_batches = self._chunk_segments(document.segments)
            review_batches = len(translation_batches) if self.options.final_review else 0
            if self.options.dry_run:
                self.dashboard.set_total_steps(2)
            else:
                total_steps = 2 + len(translation_batches) + 1 + review_batches + 1
                self.dashboard.set_total_steps(total_steps)
            self.dashboard.mark_done("PARSE")

            if self.options.dry_run:
                return PipelineResult(
                    output_path=None,
                    batches_translated=0,
                    review_batches=0,
                    usage=self.dashboard.usage,
                    dry_run=True,
                    planned_batches=self._build_batch_plan(translation_batches),
                    state_path=self.runtime_paths.state_path,
                    glossary_path=self.runtime_paths.glossary_path,
                )

            resume = self._load_resume_state(review_batches)
            translated_segments = self._translate_document(document, translation_batches, resume)

            self.dashboard.mark_running("VALIDATE")
            validate_full_alignment(document.segments, translated_segments)
            self.dashboard.mark_done("VALIDATE")

            reviewed_segments = translated_segments
            if self.options.final_review and translated_segments:
                reviewed_segments = self._review_document(document, translated_segments, resume)
                validate_full_alignment(document.segments, reviewed_segments)

            output_segments = self._build_output_segments(document, reviewed_segments)
            self.dashboard.mark_running("WRITE_OUTPUT")
            rendered = render_document(document, output_segments, bilingual=self.options.bilingual)
            self.output_path.write_text(rendered, encoding="utf-8")
            self.dashboard.mark_done("WRITE_OUTPUT")
            self.dashboard.clear_batch()
            self._save_run_state(
                translated_segments=translated_segments,
                reviewed_segments=reviewed_segments,
                translation_batches_completed=len(translation_batches),
                review_batches_completed=review_batches if self.options.final_review else 0,
            )

        return PipelineResult(
            output_path=self.output_path,
            batches_translated=len(translation_batches),
            review_batches=len(translation_batches) if self.options.final_review else 0,
            usage=self.dashboard.usage,
            cache_hits=self.cache_hits,
            state_path=self.runtime_paths.state_path,
            glossary_path=self.runtime_paths.glossary_path,
        )

    def _translate_document(
        self,
        document: SubtitleDocument,
        translation_batches: list[list[SubtitleSegment]],
        resume: ResumeSnapshot,
    ) -> list[SubtitleSegment]:
        translated_segments: list[SubtitleSegment] = list(resume.translated_segments)
        total_batches = len(translation_batches)
        for batch_index, batch_segments in enumerate(
            translation_batches[resume.translation_batches_completed :],
            start=resume.translation_batches_completed + 1,
        ):
            label = f"TRANSLATE_BATCH {batch_index}/{total_batches}"
            self.dashboard.mark_running("TRANSLATE_BATCH", label=label)
            started_at = perf_counter()
            batch_result, usage = self._translate_batch_with_retry(batch_segments, batch_index)
            latency = perf_counter() - started_at
            self.dashboard.set_batch(batch_index, total_batches, latency, label)
            self.dashboard.add_usage(usage)
            self.memory.update(batch_result.summary, batch_result.glossary_updates)
            self.glossary_store.save(self.memory.glossary)
            translated_segments.extend(
                self._materialize_translations(batch_segments, batch_result.lines)
            )
            self._save_run_state(
                translated_segments=translated_segments,
                reviewed_segments=resume.reviewed_segments,
                translation_batches_completed=batch_index,
                review_batches_completed=resume.review_batches_completed,
            )
            self.dashboard.mark_done("TRANSLATE_BATCH")
        return translated_segments

    def _review_document(
        self,
        document: SubtitleDocument,
        translated_segments: list[SubtitleSegment],
        resume: ResumeSnapshot,
    ) -> list[SubtitleSegment]:
        reviewed_segments: list[SubtitleSegment] = list(resume.reviewed_segments)
        slices = self._zip_batches(document.segments, translated_segments)
        total_batches = len(slices)
        for batch_index, batch in enumerate(
            slices[resume.review_batches_completed :],
            start=resume.review_batches_completed + 1,
        ):
            label = f"FINAL_REVIEW {batch_index}/{total_batches}"
            self.dashboard.mark_running("FINAL_REVIEW", label=label)
            started_at = perf_counter()
            review_result, usage = self._review_batch_with_retry(
                batch.source,
                batch.translated,
                batch_index,
            )
            latency = perf_counter() - started_at
            self.dashboard.set_batch(batch_index, total_batches, latency, label)
            self.dashboard.add_usage(usage)
            reviewed_segments.extend(
                self._materialize_translations(batch.source, review_result.lines)
            )
            self._save_run_state(
                translated_segments=translated_segments,
                reviewed_segments=reviewed_segments,
                translation_batches_completed=len(slices),
                review_batches_completed=batch_index,
            )
            self.dashboard.mark_done("FINAL_REVIEW")
        return reviewed_segments

    def _translate_batch_with_retry(
        self,
        batch_segments: list[SubtitleSegment],
        batch_index: int,
    ) -> tuple[BatchTranslationResult, Usage]:
        attempts = self.options.retries + 1
        last_error: Exception | None = None
        attempt_logs: list[dict] = []
        last_request_hash = ""
        for attempt in range(1, attempts + 1):
            payload: dict | None = None
            usage = Usage()
            cached = False
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
                request_hash = build_request_hash(
                    provider=self.options.provider,
                    model=self.options.model,
                    stage="translate",
                    messages=messages,
                )
                last_request_hash = request_hash
                if self.options.use_cache:
                    cached_entry = self.cache_store.load("translate", request_hash)
                    if cached_entry is not None:
                        payload, _ = cached_entry
                        usage = Usage()
                        cached = True
                        self.cache_hits += 1
                if payload is None:
                    payload, usage = self._require_backend().generate_json(messages)
                lines = parse_translation_lines(payload.get("lines", []))
                validate_translation_batch(batch_segments, lines)
                glossary_updates = parse_glossary_entries(payload.get("glossary_updates", []))
                result = BatchTranslationResult(
                    lines=lines,
                    summary=str(payload.get("summary", "")).strip(),
                    glossary_updates=glossary_updates,
                )
                if self.options.use_cache and not cached:
                    self.cache_store.save("translate", request_hash, payload, usage)
                return result, usage
            except Exception as exc:
                last_error = exc
                attempt_logs.append(
                    {
                        "attempt": attempt,
                        "cached": cached,
                        "error": str(exc),
                        "payload": payload,
                        "messages": messages,
                    }
                )
                if attempt == attempts:
                    failure_path = self.failure_store.write(
                        stage="translate",
                        batch_index=batch_index,
                        request_hash=last_request_hash,
                        batch_segments=batch_segments,
                        messages=messages,
                        attempts=attempt_logs,
                    )
                    raise RuntimeError(
                        f"Translation batch failed after {attempts} attempts. Failure sample saved to {failure_path}."
                    ) from exc
        raise RuntimeError("Translation batch retry loop ended unexpectedly.")

    def _review_batch_with_retry(
        self,
        source_segments: list[SubtitleSegment],
        translated_segments: list[SubtitleSegment],
        batch_index: int,
    ) -> tuple[ReviewResult, Usage]:
        attempts = self.options.retries + 1
        last_error: Exception | None = None
        attempt_logs: list[dict] = []
        last_request_hash = ""
        for attempt in range(1, attempts + 1):
            payload: dict | None = None
            usage = Usage()
            cached = False
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
                request_hash = build_request_hash(
                    provider=self.options.provider,
                    model=self.options.model,
                    stage="review",
                    messages=messages,
                )
                last_request_hash = request_hash
                if self.options.use_cache:
                    cached_entry = self.cache_store.load("review", request_hash)
                    if cached_entry is not None:
                        payload, _ = cached_entry
                        usage = Usage()
                        cached = True
                        self.cache_hits += 1
                if payload is None:
                    payload, usage = self._require_backend().generate_json(messages)
                lines = parse_translation_lines(payload.get("lines", []))
                validate_translation_batch(source_segments, lines)
                result = ReviewResult(
                    lines=lines,
                    review_notes=str(payload.get("review_notes", "")).strip(),
                )
                if self.options.use_cache and not cached:
                    self.cache_store.save("review", request_hash, payload, usage)
                return result, usage
            except Exception as exc:
                last_error = exc
                attempt_logs.append(
                    {
                        "attempt": attempt,
                        "cached": cached,
                        "error": str(exc),
                        "payload": payload,
                        "messages": messages,
                    }
                )
                if attempt == attempts:
                    failure_path = self.failure_store.write(
                        stage="review",
                        batch_index=batch_index,
                        request_hash=last_request_hash,
                        batch_segments=source_segments,
                        translated_segments=translated_segments,
                        messages=messages,
                        attempts=attempt_logs,
                    )
                    raise RuntimeError(
                        f"Final review batch failed after {attempts} attempts. Failure sample saved to {failure_path}."
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

    def _build_batch_plan(self, batches: list[list[SubtitleSegment]]) -> list[BatchPlanEntry]:
        plans: list[BatchPlanEntry] = []
        for index, batch in enumerate(batches, start=1):
            if not batch:
                continue
            plans.append(
                BatchPlanEntry(
                    index=index,
                    size=len(batch),
                    first_id=batch[0].id,
                    last_id=batch[-1].id,
                )
            )
        return plans

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

    def _load_resume_state(self, review_batches: int) -> ResumeSnapshot:
        if not self.options.resume or self.state_store is None:
            self._load_persistent_glossary()
            return ResumeSnapshot()

        snapshot = self.state_store.load()
        if snapshot is None:
            self._load_persistent_glossary()
            return ResumeSnapshot()

        self.memory = snapshot.memory
        self.dashboard.restore_usage(snapshot.usage)
        self.dashboard.restore_progress(
            self._restored_completed_steps(
                translation_batches_completed=snapshot.translation_batches_completed,
                review_batches_completed=snapshot.review_batches_completed,
                review_batches=review_batches,
            )
        )
        return snapshot

    def _load_persistent_glossary(self) -> None:
        glossary = self.glossary_store.load()
        if glossary:
            self.memory.load_glossary(glossary)

    def _restored_completed_steps(
        self,
        translation_batches_completed: int,
        review_batches_completed: int,
        review_batches: int,
    ) -> int:
        completed_steps = 2 + translation_batches_completed
        if review_batches > 0 and translation_batches_completed >= review_batches:
            completed_steps += 1 + review_batches_completed
        return completed_steps

    def _save_run_state(
        self,
        *,
        translated_segments: list[SubtitleSegment],
        reviewed_segments: list[SubtitleSegment],
        translation_batches_completed: int,
        review_batches_completed: int,
    ) -> None:
        if self.options.dry_run or self.state_store is None or self.input_signature is None:
            return
        self.state_store.save(
            options=self.options,
            output_path=self.output_path,
            input_signature=self.input_signature,
            translated_segments=translated_segments,
            reviewed_segments=reviewed_segments,
            usage=self.dashboard.usage,
            memory=self.memory,
            translation_batches_completed=translation_batches_completed,
            review_batches_completed=review_batches_completed,
        )

    def _require_backend(self) -> LLMBackend:
        if self.backend is None:
            raise RuntimeError("No backend configured. Disable --dry-run or provide a backend.")
        return self.backend
