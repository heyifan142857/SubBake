from __future__ import annotations

import json

from subbake.entities import SubtitleSegment
from subbake.memory import ContextMemory


def select_relevant_glossary(
    glossary: dict[str, str],
    texts: list[str],
    limit: int = 24,
) -> dict[str, str]:
    if not glossary or not texts:
        return {}

    haystack = "\n".join(texts).casefold()
    matched: dict[str, str] = {}
    for source, target in glossary.items():
        if source.casefold() in haystack or target.casefold() in haystack:
            matched[source] = target
            if len(matched) >= limit:
                break
    return matched


def build_translation_messages(
    batch_segments: list[SubtitleSegment],
    memory: ContextMemory,
    source_language: str,
    target_language: str,
) -> list[dict[str, str]]:
    batch_texts = [segment.text for segment in batch_segments if segment.text]
    context_payload = {
        "src": source_language,
        "tgt": target_language,
        "rules": list(memory.style_rules),
    }
    structure_notes = _translation_structure_notes(batch_segments)
    if structure_notes:
        context_payload["structure_notes"] = structure_notes
    recent = list(memory.recent_summaries[-memory.max_summaries :])
    if recent:
        context_payload["recent"] = recent
    glossary = select_relevant_glossary(memory.glossary, batch_texts)
    if glossary:
        context_payload["glossary"] = glossary

    system_prompt = (
        "You are a professional subtitle translator.\n"
        "Return valid JSON only.\n"
        "Keep subtitle order, count, and ids exact.\n"
        "Never merge, drop, or insert subtitle entries even when the spoken sentence spans multiple subtitle lines.\n"
        "Every non-empty source entry must produce one non-empty translated entry with the same id."
    )
    batch_payload = {
        "lines": [
            {
                "id": segment.id,
                "text": segment.text,
            }
            for segment in batch_segments
        ]
    }
    user_prompt = (
        "TASK_START\n"
        "translate_subtitles\n"
        "TASK_END\n"
        "Translate each line into the target language.\n"
        "Preserve line count, order, and ids exactly.\n"
        "Even if one spoken sentence spans multiple subtitle entries, keep each subtitle entry separate.\n"
        "Never merge neighboring lines to complete a sentence.\n"
        "If a line is only a fragment like 'and ...' or 'that ...', still translate that line alone and keep its id.\n"
        "Do not move words from one subtitle id into another subtitle id.\n"
        "Do not absorb a short fragment into the previous or next entry.\n"
        "Keep blank lines blank. Keep tone, slang, and profanity intact.\n"
        "Favor natural subtitle phrasing over literal wording.\n"
        'Return JSON only with keys "lines", "summary", and "glossary_updates".\n'
        "CONTEXT_JSON_START\n"
        f"{_compact_json(context_payload)}\n"
        "CONTEXT_JSON_END\n"
        "BATCH_JSON_START\n"
        f"{_compact_json(batch_payload)}\n"
        "BATCH_JSON_END\n"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_review_messages(
    source_segments: list[SubtitleSegment],
    translated_segments: list[SubtitleSegment],
    memory: ContextMemory,
    target_language: str,
    reasons: list[str],
) -> list[dict[str, str]]:
    source_texts = [segment.text for segment in source_segments if segment.text]
    translated_texts = [segment.text for segment in translated_segments if segment.text]
    relevant_glossary = select_relevant_glossary(
        memory.glossary,
        source_texts + translated_texts,
    )
    system_prompt = (
        "You are performing a targeted subtitle QA review.\n"
        "Return valid JSON only.\n"
        "Only fix terminology, consistency, and readability issues without changing the number of entries."
    )
    review_payload = {
        "tgt": target_language,
        "reasons": reasons,
        "lines": [
            {
                "id": source.id,
                "translation": translated.text,
            }
            for source, translated in zip(source_segments, translated_segments, strict=True)
        ],
    }
    recent = list(memory.recent_summaries[-memory.max_summaries :])
    if recent:
        review_payload["recent"] = recent
    if relevant_glossary:
        review_payload["glossary"] = relevant_glossary
    focus_lines = [
        {
            "id": source.id,
            "source": source.text,
            "translation": translated.text,
        }
        for source, translated in zip(source_segments, translated_segments, strict=True)
        if _needs_source_context(source.text)
    ]
    if focus_lines:
        review_payload["focus"] = focus_lines

    user_prompt = (
        "TASK_START\n"
        "review_translations\n"
        "TASK_END\n"
        "Review only this high-risk batch.\n"
        "Do not remove, reorder, merge, or renumber entries.\n"
        "Prefer minimal edits; leave good lines untouched.\n"
        'Return JSON only with keys "lines" and "review_notes".\n'
        "REVIEW_JSON_START\n"
        f"{_compact_json(review_payload)}\n"
        "REVIEW_JSON_END\n"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _compact_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _needs_source_context(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if "\n" in stripped:
        return True
    if any(marker in stripped for marker in ("<", ">", "{", "}", ">>")):
        return True
    if stripped.startswith(("-", "–", "—")):
        return True
    return any(character.isupper() for character in stripped)


def _translation_structure_notes(batch_segments: list[SubtitleSegment]) -> list[str]:
    notes: list[str] = []
    if any(
        _is_continuation_line(next_segment.text) and not _ends_sentence(current_segment.text)
        for current_segment, next_segment in zip(batch_segments, batch_segments[1:], strict=False)
    ):
        notes.append(
            "Some neighboring subtitle entries are fragments of the same spoken sentence. Translate each entry separately and keep every original id."
        )
        notes.append(
            "Do not combine neighboring fragments into one fluent sentence. Each original subtitle entry still needs its own non-empty translation."
        )
    if any(not segment.text.strip() for segment in batch_segments):
        notes.append("Blank subtitle entries must stay blank in the output.")
    return notes


def _is_continuation_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0].islower():
        return True
    lowered = stripped.casefold()
    return lowered.startswith(
        (
            "and ",
            "but ",
            "or ",
            "so ",
            "that ",
            "which ",
            "who ",
            "because ",
            "if ",
            "when ",
            "then ",
            "to ",
        )
    )


def _ends_sentence(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return stripped.endswith((".", "!", "?", "。", "！", "？", "…"))
