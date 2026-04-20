from __future__ import annotations

import re
from pathlib import Path

from subbake.entities import SubtitleDocument, SubtitleSegment

TIMESTAMP_SEPARATOR = "-->"


def parse_srt_document(path: Path) -> SubtitleDocument:
    raw_text = path.read_text(encoding="utf-8-sig")
    normalized = raw_text.replace("\r\n", "\n").strip()
    if not normalized:
        return SubtitleDocument(path=path, format="srt", segments=[])

    blocks = re.split(r"\n\s*\n", normalized)
    segments: list[SubtitleSegment] = []
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines()]
        if len(lines) < 3 or TIMESTAMP_SEPARATOR not in lines[1]:
            raise ValueError(f"Malformed SRT block:\n{block}")
        subtitle_id = lines[0].strip()
        start, end = [part.strip() for part in lines[1].split(TIMESTAMP_SEPARATOR, maxsplit=1)]
        text = "\n".join(lines[2:])
        segments.append(
            SubtitleSegment(
                id=subtitle_id,
                identifier=subtitle_id,
                start=start,
                end=end,
                text=text,
            )
        )

    return SubtitleDocument(path=path, format="srt", segments=segments)


def render_srt_document(segments: list[SubtitleSegment], bilingual: bool) -> str:
    _ = bilingual
    blocks: list[str] = []
    for segment in segments:
        blocks.append(
            "\n".join(
                [
                    segment.identifier or segment.id,
                    f"{segment.start} {TIMESTAMP_SEPARATOR} {segment.end}",
                    segment.text,
                ]
            ).rstrip()
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")
