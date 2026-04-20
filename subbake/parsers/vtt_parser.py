from __future__ import annotations

import re
from pathlib import Path

from subbake.entities import PassthroughBlock, SubtitleDocument, SubtitleSegment

TIMESTAMP_SEPARATOR = "-->"
TIMING_LINE_RE = re.compile(
    r"^(?P<start>\S+)\s+-->\s+(?P<end>\S+)(?P<settings>(?:[ \t].*)?)$"
)


def parse_vtt_document(path: Path) -> SubtitleDocument:
    raw_text = path.read_text(encoding="utf-8-sig")
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise ValueError("Malformed VTT file: missing WEBVTT header.")

    lines = normalized.splitlines()
    header = lines[0].strip()
    if not header.startswith("WEBVTT"):
        raise ValueError("Malformed VTT file: first line must start with WEBVTT.")

    body = "\n".join(lines[1:]).strip()
    if not body:
        return SubtitleDocument(path=path, format="vtt", segments=[], header=header)

    blocks = re.split(r"\n\s*\n", body)
    segments: list[SubtitleSegment] = []
    passthrough_blocks: list[PassthroughBlock] = []
    for block in blocks:
        cue = _parse_vtt_cue(block, cue_index=len(segments) + 1)
        if cue is None:
            passthrough_blocks.append(
                PassthroughBlock(
                    insert_before=len(segments),
                    content=block.strip(),
                )
            )
            continue
        segments.append(cue)

    return SubtitleDocument(
        path=path,
        format="vtt",
        segments=segments,
        header=header,
        passthrough_blocks=passthrough_blocks,
    )


def render_vtt_document(
    document: SubtitleDocument,
    segments: list[SubtitleSegment],
    bilingual: bool,
) -> str:
    _ = bilingual
    blocks: list[str] = []
    passthrough_by_index: dict[int, list[str]] = {}
    for block in document.passthrough_blocks:
        passthrough_by_index.setdefault(block.insert_before, []).append(block.content.rstrip())

    for index in range(len(segments) + 1):
        blocks.extend(passthrough_by_index.get(index, []))
        if index == len(segments):
            continue

        segment = segments[index]
        cue_lines: list[str] = []
        if segment.identifier:
            cue_lines.append(segment.identifier)

        timing_line = f"{segment.start} {TIMESTAMP_SEPARATOR} {segment.end}"
        if segment.settings:
            timing_line = f"{timing_line} {segment.settings}"
        cue_lines.append(timing_line)

        if segment.text:
            cue_lines.extend(segment.text.split("\n"))
        else:
            cue_lines.append("")

        blocks.append("\n".join(cue_lines).rstrip())

    header = document.header or "WEBVTT"
    if not blocks:
        return f"{header}\n"
    return f"{header}\n\n" + "\n\n".join(blocks) + "\n"


def _parse_vtt_cue(block: str, cue_index: int) -> SubtitleSegment | None:
    lines = [line.rstrip() for line in block.splitlines()]
    if not lines:
        return None

    identifier: str | None = None
    timing_line = lines[0]
    if TIMESTAMP_SEPARATOR not in timing_line:
        if len(lines) < 2:
            return None
        identifier = lines[0].strip() or None
        timing_line = lines[1]
        text_lines = lines[2:]
    else:
        text_lines = lines[1:]

    timing = _parse_timing_line(timing_line)
    if timing is None:
        return None

    return SubtitleSegment(
        id=str(cue_index),
        identifier=identifier,
        start=timing["start"],
        end=timing["end"],
        settings=timing["settings"],
        text="\n".join(text_lines),
    )


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
