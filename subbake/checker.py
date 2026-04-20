from __future__ import annotations

from subbake.entities import SubtitleSegment, TranslationLine


class ValidationError(ValueError):
    """Raised when model output does not match subtitle structure."""


def validate_translation_batch(
    source_segments: list[SubtitleSegment],
    translated_lines: list[TranslationLine],
) -> None:
    if len(source_segments) != len(translated_lines):
        raise ValidationError(
            f"Line count mismatch: expected {len(source_segments)} lines, received {len(translated_lines)}."
        )

    for source, translated in zip(source_segments, translated_lines, strict=True):
        if str(source.id) != str(translated.id):
            raise ValidationError(
                f"ID mismatch: expected {source.id}, received {translated.id}."
            )
        if source.text.strip() and not translated.translation.strip():
            raise ValidationError(f"Empty translation for subtitle id {source.id}.")


def validate_full_alignment(
    source_segments: list[SubtitleSegment],
    translated_segments: list[SubtitleSegment],
) -> None:
    if len(source_segments) != len(translated_segments):
        raise ValidationError(
            f"Translated document has {len(translated_segments)} lines; expected {len(source_segments)}."
        )
    seen_ids: set[str] = set()
    for source, translated in zip(source_segments, translated_segments, strict=True):
        if source.id != translated.id:
            raise ValidationError(
                f"Output order mismatch: expected id {source.id}, received {translated.id}."
            )
        if translated.id in seen_ids:
            raise ValidationError(f"Duplicate subtitle id found in output: {translated.id}.")
        seen_ids.add(translated.id)
