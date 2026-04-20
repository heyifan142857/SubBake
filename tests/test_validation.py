from __future__ import annotations

import unittest

from subbake.checker import ValidationError, validate_full_alignment, validate_translation_batch
from subbake.entities import SubtitleSegment, TranslationLine


class ValidationTestCase(unittest.TestCase):
    def test_validate_translation_batch_rejects_mismatched_ids(self) -> None:
        with self.assertRaises(ValidationError):
            validate_translation_batch(
                source_segments=[SubtitleSegment(id="1", text="Hello")],
                translated_lines=[TranslationLine(id="2", translation="你好")],
            )

    def test_validate_full_alignment_rejects_duplicates(self) -> None:
        with self.assertRaises(ValidationError):
            validate_full_alignment(
                source_segments=[
                    SubtitleSegment(id="1", text="a"),
                    SubtitleSegment(id="2", text="b"),
                ],
                translated_segments=[
                    SubtitleSegment(id="1", text="甲"),
                    SubtitleSegment(id="1", text="乙"),
                ],
            )
