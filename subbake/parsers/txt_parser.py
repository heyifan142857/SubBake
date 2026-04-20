from __future__ import annotations

from pathlib import Path

from subbake.entities import SubtitleDocument, SubtitleSegment


def parse_txt_document(path: Path) -> SubtitleDocument:
    raw_text = path.read_text(encoding="utf-8-sig")
    lines = raw_text.splitlines()
    segments = [
        SubtitleSegment(id=str(index), text=line)
        for index, line in enumerate(lines, start=1)
    ]
    return SubtitleDocument(path=path, format="txt", segments=segments)


def render_txt_document(
    source_segments: list[SubtitleSegment],
    translated_segments: list[SubtitleSegment],
    bilingual: bool,
) -> str:
    source_by_id = {segment.id: segment for segment in source_segments}
    rendered_lines: list[str] = []
    for translated in translated_segments:
        if bilingual:
            source_text = source_by_id[translated.id].text
            rendered_lines.append(source_text)
        rendered_lines.append(translated.text)
    return "\n".join(rendered_lines) + ("\n" if rendered_lines else "")
