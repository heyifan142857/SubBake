from pathlib import Path

from subbake.entities import SubtitleDocument, SubtitleSegment
from subbake.parsers.srt_parser import parse_srt_document, render_srt_document
from subbake.parsers.txt_parser import parse_txt_document, render_txt_document
from subbake.parsers.vtt_parser import parse_vtt_document, render_vtt_document


def load_document(path: Path) -> SubtitleDocument:
    suffix = path.suffix.lower()
    if suffix == ".srt":
        return parse_srt_document(path)
    if suffix == ".vtt":
        return parse_vtt_document(path)
    if suffix == ".txt":
        return parse_txt_document(path)
    raise ValueError(f"Unsupported input format: {suffix}")


def render_document(
    document: SubtitleDocument,
    translations: list[SubtitleSegment],
    bilingual: bool,
    output_format: str | None = None,
) -> str:
    target_format = output_format or document.format
    if target_format == "srt":
        return render_srt_document(translations, bilingual=bilingual)
    if target_format == "vtt":
        vtt_document = SubtitleDocument(
            path=document.path,
            format="vtt",
            segments=document.segments,
            header=document.header if document.format == "vtt" else "WEBVTT",
            passthrough_blocks=document.passthrough_blocks if document.format == "vtt" else [],
        )
        return render_vtt_document(vtt_document, translations, bilingual=bilingual)
    if target_format == "txt":
        return render_txt_document(document.segments, translations, bilingual=bilingual)
    raise ValueError(f"Unsupported output format: {target_format}")
