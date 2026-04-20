from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from subbake.entities import PipelineOptions, SubtitleSegment, Usage
from subbake.memory import ContextMemory

RUN_STATE_VERSION = 1
CACHE_VERSION = 1


@dataclass(slots=True)
class RuntimePaths:
    root_dir: Path
    run_dir: Path
    cache_dir: Path
    state_path: Path
    glossary_path: Path
    failures_dir: Path


@dataclass(slots=True)
class ResumeSnapshot:
    translated_segments: list[SubtitleSegment] = field(default_factory=list)
    reviewed_segments: list[SubtitleSegment] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    memory: ContextMemory = field(default_factory=ContextMemory)
    translation_batches_completed: int = 0
    review_batches_completed: int = 0


def build_runtime_paths(
    input_path: Path,
    work_dir: Path | None = None,
    glossary_path: Path | None = None,
) -> RuntimePaths:
    root_dir = work_dir or input_path.parent / ".subbake"
    safe_stem = _slugify(input_path.stem or "input")
    input_key = _stable_hash({"path": str(input_path.resolve())})[:12]
    run_dir = root_dir / "runs" / f"{safe_stem}-{input_key}"
    return RuntimePaths(
        root_dir=root_dir,
        run_dir=run_dir,
        cache_dir=root_dir / "cache",
        state_path=run_dir / "run_state.json",
        glossary_path=glossary_path or root_dir / "glossary.json",
        failures_dir=run_dir / "failures",
    )


def compute_input_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    return {
        "sha1": digest,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def build_pipeline_fingerprint(
    options: PipelineOptions,
    input_signature: dict[str, Any],
) -> str:
    payload = {
        "version": RUN_STATE_VERSION,
        "input_signature": input_signature,
        "input_format": options.input_path.suffix.lower(),
        "provider": options.provider,
        "model": options.model,
        "batch_size": options.batch_size,
        "source_language": options.source_language,
        "target_language": options.target_language,
        "final_review": options.final_review,
        "bilingual": options.bilingual,
    }
    return _stable_hash(payload)


def build_request_hash(
    provider: str,
    model: str,
    stage: str,
    messages: list[dict[str, str]],
) -> str:
    payload = {
        "version": CACHE_VERSION,
        "provider": provider.lower(),
        "model": model,
        "stage": stage,
        "messages": messages,
    }
    return _stable_hash(payload)


class CacheStore:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    def load(self, stage: str, request_hash: str) -> tuple[dict, Usage] | None:
        path = self.cache_dir / stage / f"{request_hash}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return dict(data["payload"]), _usage_from_dict(data.get("usage", {}))

    def save(self, stage: str, request_hash: str, payload: dict, usage: Usage) -> None:
        path = self.cache_dir / stage / f"{request_hash}.json"
        _write_json(
            path,
            {
                "payload": payload,
                "usage": _usage_to_dict(usage),
            },
        )


class GlossaryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            str(key): str(value)
            for key, value in dict(data).items()
        }

    def save(self, glossary: dict[str, str]) -> None:
        _write_json(self.path, glossary)


class RunStateStore:
    def __init__(self, path: Path, pipeline_fingerprint: str) -> None:
        self.path = path
        self.pipeline_fingerprint = pipeline_fingerprint

    def load(self) -> ResumeSnapshot | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != RUN_STATE_VERSION:
            return None
        if data.get("pipeline_fingerprint") != self.pipeline_fingerprint:
            return None
        return ResumeSnapshot(
            translated_segments=[
                _segment_from_dict(item)
                for item in data.get("translated_segments", [])
            ],
            reviewed_segments=[
                _segment_from_dict(item)
                for item in data.get("reviewed_segments", [])
            ],
            usage=_usage_from_dict(data.get("usage", {})),
            memory=ContextMemory.from_dict(data.get("memory", {})),
            translation_batches_completed=int(data.get("translation_batches_completed", 0)),
            review_batches_completed=int(data.get("review_batches_completed", 0)),
        )

    def save(
        self,
        *,
        options: PipelineOptions,
        output_path: Path | None,
        input_signature: dict[str, Any],
        translated_segments: list[SubtitleSegment],
        reviewed_segments: list[SubtitleSegment],
        usage: Usage,
        memory: ContextMemory,
        translation_batches_completed: int,
        review_batches_completed: int,
    ) -> None:
        payload = {
            "version": RUN_STATE_VERSION,
            "pipeline_fingerprint": self.pipeline_fingerprint,
            "input_path": str(options.input_path),
            "output_path": str(output_path) if output_path is not None else None,
            "input_signature": input_signature,
            "provider": options.provider,
            "model": options.model,
            "batch_size": options.batch_size,
            "translation_batches_completed": translation_batches_completed,
            "review_batches_completed": review_batches_completed,
            "translated_segments": [_segment_to_dict(item) for item in translated_segments],
            "reviewed_segments": [_segment_to_dict(item) for item in reviewed_segments],
            "usage": _usage_to_dict(usage),
            "memory": memory.to_dict(),
        }
        _write_json(self.path, payload)


class FailureStore:
    def __init__(self, failures_dir: Path) -> None:
        self.failures_dir = failures_dir

    def write(
        self,
        *,
        stage: str,
        batch_index: int,
        request_hash: str,
        batch_segments: list[SubtitleSegment],
        messages: list[dict[str, str]],
        attempts: list[dict[str, Any]],
        translated_segments: list[SubtitleSegment] | None = None,
    ) -> Path:
        path = self.failures_dir / f"{stage}_batch_{batch_index:04d}.json"
        payload = {
            "stage": stage,
            "batch_index": batch_index,
            "request_hash": request_hash,
            "batch_segments": [_segment_to_dict(item) for item in batch_segments],
            "messages": messages,
            "translated_segments": [
                _segment_to_dict(item)
                for item in (translated_segments or [])
            ],
            "attempts": attempts,
        }
        _write_json(path, payload)
        return path


def _segment_to_dict(segment: SubtitleSegment) -> dict[str, Any]:
    return {
        "id": segment.id,
        "text": segment.text,
        "start": segment.start,
        "end": segment.end,
        "identifier": segment.identifier,
        "settings": segment.settings,
    }


def _segment_from_dict(data: dict[str, Any]) -> SubtitleSegment:
    return SubtitleSegment(
        id=str(data["id"]),
        text=str(data["text"]),
        start=data.get("start"),
        end=data.get("end"),
        identifier=data.get("identifier"),
        settings=data.get("settings"),
    )


def _usage_to_dict(usage: Usage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def _usage_from_dict(data: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=int(data.get("input_tokens", 0)),
        output_tokens=int(data.get("output_tokens", 0)),
        total_tokens=int(data.get("total_tokens", 0)),
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug or "input"


def _stable_hash(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)
