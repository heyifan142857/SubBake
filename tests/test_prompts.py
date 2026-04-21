from __future__ import annotations

import json
import unittest

from subbake.entities import SubtitleSegment
from subbake.memory import ContextMemory
from subbake.prompts import build_review_messages, build_translation_messages


class PromptTestCase(unittest.TestCase):
    def test_translation_prompt_uses_compact_payload_without_timestamps(self) -> None:
        memory = ContextMemory()
        memory.recent_summaries = ["summary"]
        memory.glossary = {
            "Alice": "爱丽丝",
            "Unused": "未使用",
        }

        messages = build_translation_messages(
            batch_segments=[
                SubtitleSegment(id="1", text="Hello Alice.", start="00:00:01", end="00:00:02"),
                SubtitleSegment(id="2", text="Move."),
            ],
            memory=memory,
            source_language="English",
            target_language="Chinese",
        )

        user_prompt = messages[1]["content"]
        self.assertNotIn('"start"', user_prompt)
        self.assertNotIn('"end"', user_prompt)

        context = self._extract_json_block(user_prompt, "CONTEXT_JSON_START", "CONTEXT_JSON_END")
        batch = self._extract_json_block(user_prompt, "BATCH_JSON_START", "BATCH_JSON_END")

        self.assertEqual(context["src"], "English")
        self.assertEqual(context["glossary"], {"Alice": "爱丽丝"})
        self.assertEqual(batch["lines"][0], {"id": "1", "text": "Hello Alice."})

    def test_translation_prompt_explicitly_forbids_merging_split_sentences(self) -> None:
        messages = build_translation_messages(
            batch_segments=[
                SubtitleSegment(id="1", text="I thought"),
                SubtitleSegment(id="2", text="we could still make it"),
            ],
            memory=ContextMemory(),
            source_language="English",
            target_language="Chinese",
        )

        user_prompt = messages[1]["content"]
        context = self._extract_json_block(user_prompt, "CONTEXT_JSON_START", "CONTEXT_JSON_END")

        self.assertIn("Never merge neighboring lines to complete a sentence.", user_prompt)
        self.assertIn("Do not absorb a short fragment into the previous or next entry.", user_prompt)
        self.assertEqual(
            context["structure_notes"],
            [
                "Some neighboring subtitle entries are fragments of the same spoken sentence. Translate each entry separately and keep every original id.",
                "Do not combine neighboring fragments into one fluent sentence. Each original subtitle entry still needs its own non-empty translation.",
            ],
        )

    def test_review_prompt_only_includes_source_focus_for_risky_lines(self) -> None:
        memory = ContextMemory()
        memory.glossary = {"Alice": "爱丽丝"}

        messages = build_review_messages(
            source_segments=[
                SubtitleSegment(id="1", text="Hello Alice."),
                SubtitleSegment(id="2", text="keep moving."),
            ],
            translated_segments=[
                SubtitleSegment(id="1", text="你好 Alice。"),
                SubtitleSegment(id="2", text="继续前进。"),
            ],
            memory=memory,
            target_language="Chinese",
            reasons=["names and terms"],
        )

        payload = self._extract_json_block(messages[1]["content"], "REVIEW_JSON_START", "REVIEW_JSON_END")

        self.assertEqual(payload["glossary"], {"Alice": "爱丽丝"})
        self.assertEqual(
            payload["lines"],
            [
                {"id": "1", "translation": "你好 Alice。"},
                {"id": "2", "translation": "继续前进。"},
            ],
        )
        self.assertEqual(
            payload["focus"],
            [{"id": "1", "source": "Hello Alice.", "translation": "你好 Alice。"}],
        )

    def test_fast_translation_prompt_uses_lighter_context(self) -> None:
        memory = ContextMemory()
        memory.recent_summaries = ["summary"]
        memory.glossary = {"Alice": "爱丽丝"}

        messages = build_translation_messages(
            batch_segments=[SubtitleSegment(id="1", text="Hello Alice.")],
            memory=memory,
            source_language="English",
            target_language="Japanese",
            fast_mode=True,
        )

        user_prompt = messages[1]["content"]
        context = self._extract_json_block(user_prompt, "CONTEXT_JSON_START", "CONTEXT_JSON_END")

        self.assertEqual(context, {"src": "English", "tgt": "Japanese"})
        self.assertIn("Best-effort speed mode", user_prompt)
        self.assertIn("Translate into Japanese.", messages[0]["content"])

    def _extract_json_block(self, text: str, start_marker: str, end_marker: str) -> dict:
        start_index = text.index(start_marker) + len(start_marker)
        end_index = text.index(end_marker, start_index)
        return json.loads(text[start_index:end_index].strip())
