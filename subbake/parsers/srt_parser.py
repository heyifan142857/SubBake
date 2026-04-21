from __future__ import annotations

import re
from pathlib import Path

from subbake.entities import SubtitleDocument, SubtitleSegment

TIMESTAMP_SEPARATOR = "-->"
TIMING_LINE_RE = re.compile(
    r"^(?P<start>\S+)\s*-->\s*(?P<end>\S+)(?P<settings>(?:[ \t].*)?)$"
)


def parse_srt_document(path: Path) -> SubtitleDocument:
    raw_text = path.read_text(encoding="utf-8-sig")
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return SubtitleDocument(path=path, format="srt", segments=[])

    blocks = re.split(r"\n\s*\n", normalized)
    segments: list[SubtitleSegment] = []
    for cue_index, block in enumerate(blocks, start=1):
        segments.append(_parse_srt_block(block, cue_index))

    return SubtitleDocument(path=path, format="srt", segments=segments)


def render_srt_document(segments: list[SubtitleSegment], bilingual: bool) -> str:
    _ = bilingual
    blocks: list[str] = []
    for segment in segments:
        timing_line = f"{segment.start} {TIMESTAMP_SEPARATOR} {segment.end}"
        if segment.settings:
            timing_line = f"{timing_line} {segment.settings}"
        blocks.append(
            "\n".join(
                [
                    segment.identifier or segment.id,
                    timing_line,
                    segment.text,
                ]
            ).rstrip()
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _parse_srt_block(block: str, cue_index: int) -> SubtitleSegment:
    lines = [line.rstrip() for line in block.splitlines()]
    timing_index, timing = _find_timing_line(lines)
    if timing_index is None or timing is None:
        raise ValueError(f"Malformed SRT block:\n{block}")

    prefix_lines = [line.strip() for line in lines[:timing_index] if line.strip()]
    identifier = prefix_lines[0] if prefix_lines else None
    subtitle_id = identifier or str(cue_index)
    text = "\n".join(lines[timing_index + 1 :])
    return SubtitleSegment(
        id=subtitle_id,
        identifier=identifier,
        start=timing["start"],
        end=timing["end"],
        settings=timing["settings"],
        text=text,
    )


def _find_timing_line(lines: list[str]) -> tuple[int | None, dict[str, str | None] | None]:
    for index, line in enumerate(lines):
        timing = _parse_timing_line(line)
        if timing is not None:
            return index, timing
    return None, None


def _parse_timing_line(line: str) -> dict[str, str | None] | None:
    match = TIMING_LINE_RE.match(line.strip())
    if match is None:
        return None
    settings = (match.group("settings") or "").strip() or None
    return {
        "start": match.group("start"),
        "end": match.group("end"),
        "settings": settings,
    }
