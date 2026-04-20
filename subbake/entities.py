from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SubtitleSegment:
    id: str
    text: str
    start: str | None = None
    end: str | None = None
    identifier: str | None = None
    settings: str | None = None


@dataclass(slots=True)
class PassthroughBlock:
    insert_before: int
    content: str


@dataclass(slots=True)
class SubtitleDocument:
    path: Path
    format: str
    segments: list[SubtitleSegment]
    header: str | None = None
    passthrough_blocks: list[PassthroughBlock] = field(default_factory=list)


@dataclass(slots=True)
class GlossaryEntry:
    source: str
    target: str


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens


@dataclass(slots=True)
class TranslationLine:
    id: str
    translation: str


@dataclass(slots=True)
class BatchTranslationResult:
    lines: list[TranslationLine]
    summary: str = ""
    glossary_updates: list[GlossaryEntry] = field(default_factory=list)


@dataclass(slots=True)
class ReviewResult:
    lines: list[TranslationLine]
    review_notes: str = ""


@dataclass(slots=True)
class PipelineOptions:
    input_path: Path
    output_path: Path | None = None
    provider: str = "mock"
    model: str = "mock-zh"
    batch_size: int = 50
    bilingual: bool = False
    target_language: str = "Chinese"
    source_language: str = "Auto"
    retries: int = 2
    final_review: bool = True
    timeout_seconds: float = 120.0
    api_key: str | None = None
    base_url: str | None = None


@dataclass(slots=True)
class PipelineResult:
    output_path: Path
    batches_translated: int
    review_batches: int
    usage: Usage
