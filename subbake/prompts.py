from __future__ import annotations

import json

from subbake.entities import SubtitleSegment
from subbake.memory import ContextMemory


def build_translation_messages(
    batch_segments: list[SubtitleSegment],
    memory: ContextMemory,
    source_language: str,
    target_language: str,
) -> list[dict[str, str]]:
    system_prompt = (
        "You are a professional subtitle translator.\n"
        "Translate each subtitle entry into the target language.\n"
        "Return valid JSON only.\n"
        "Preserve ordering, preserve IDs exactly, and never drop or merge entries.\n"
        "Keep the style concise for subtitles."
    )
    batch_payload = {
        "lines": [
            {
                "id": segment.id,
                "text": segment.text,
                "start": segment.start,
                "end": segment.end,
            }
            for segment in batch_segments
        ]
    }
    context_payload = {
        "source_language": source_language,
        "target_language": target_language,
        "memory": memory.snapshot(),
        "output_schema": {
            "lines": [{"id": "original id", "translation": "translated subtitle"}],
            "summary": "brief summary for the batch",
            "glossary_updates": [{"source": "Name", "target": "Chinese name"}],
        },
    }
    user_prompt = (
        "TASK_START\n"
        "translate_subtitles\n"
        "TASK_END\n"
        "Follow these rules strictly:\n"
        "- Preserve line count and order exactly.\n"
        "- Copy each input id into the output.\n"
        "- Keep blank lines blank.\n"
        "- Keep tone, slang, and profanity intact.\n"
        "- Favor natural Chinese over literal wording.\n"
        "CONTEXT_JSON_START\n"
        f"{json.dumps(context_payload, ensure_ascii=False, indent=2)}\n"
        "CONTEXT_JSON_END\n"
        "BATCH_JSON_START\n"
        f"{json.dumps(batch_payload, ensure_ascii=False, indent=2)}\n"
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
) -> list[dict[str, str]]:
    system_prompt = (
        "You are performing a final subtitle QA review.\n"
        "Return valid JSON only.\n"
        "Fix inconsistencies in names, tone, and style without changing the number of entries."
    )
    review_payload = {
        "target_language": target_language,
        "memory": memory.snapshot(),
        "lines": [
            {
                "id": source.id,
                "source": source.text,
                "translation": translated.text,
            }
            for source, translated in zip(source_segments, translated_segments, strict=True)
        ],
        "output_schema": {
            "lines": [{"id": "original id", "translation": "revised translation"}],
            "review_notes": "brief notes about fixes",
        },
    }
    user_prompt = (
        "TASK_START\n"
        "review_translations\n"
        "TASK_END\n"
        "Check consistency of names, tone, and subtitle readability.\n"
        "Do not remove, reorder, or merge entries.\n"
        "REVIEW_JSON_START\n"
        f"{json.dumps(review_payload, ensure_ascii=False, indent=2)}\n"
        "REVIEW_JSON_END\n"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
