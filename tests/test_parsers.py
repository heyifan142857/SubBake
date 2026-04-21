from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from subbake.entities import SubtitleDocument, SubtitleSegment
from subbake.parsers import render_document
from subbake.parsers.srt_parser import parse_srt_document
from subbake.parsers.txt_parser import parse_txt_document, render_txt_document
from subbake.parsers.vtt_parser import parse_vtt_document


class ParserTestCase(unittest.TestCase):
    def test_parse_and_render_srt_document(self) -> None:
        content = (
            "1\n"
            "00:00:01,000 --> 00:00:03,000\n"
            "Hello there.\n\n"
            "2\n"
            "00:00:04,000 --> 00:00:06,000\n"
            "General Kenobi.\n"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.srt"
            path.write_text(content, encoding="utf-8")

            document = parse_srt_document(path)
            rendered = render_document(document, document.segments, bilingual=False)

        self.assertEqual(document.format, "srt")
        self.assertEqual([segment.id for segment in document.segments], ["1", "2"])
        self.assertEqual(rendered, content)

    def test_render_txt_document_in_bilingual_mode(self) -> None:
        source_segments = [
            SubtitleSegment(id="1", text="Hello"),
            SubtitleSegment(id="2", text="World"),
        ]
        translated_segments = [
            SubtitleSegment(id="1", text="你好"),
            SubtitleSegment(id="2", text="世界"),
        ]

        rendered = render_txt_document(
            source_segments=source_segments,
            translated_segments=translated_segments,
            bilingual=True,
        )

        self.assertEqual(rendered, "Hello\n你好\nWorld\n世界\n")

    def test_parse_and_render_vtt_document_with_passthrough_blocks(self) -> None:
        content = (
            "WEBVTT\n\n"
            "NOTE opening note\n\n"
            "intro\n"
            "00:00:01.000 --> 00:00:03.000 line:90%\n"
            "Hello there.\n\n"
            "00:00:04.000 --> 00:00:06.000 align:start\n"
            "General Kenobi.\n"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.vtt"
            path.write_text(content, encoding="utf-8")

            document = parse_vtt_document(path)
            rendered = render_document(document, document.segments, bilingual=False)

        self.assertEqual(document.format, "vtt")
        self.assertEqual(document.header, "WEBVTT")
        self.assertEqual(len(document.passthrough_blocks), 1)
        self.assertEqual(document.passthrough_blocks[0].content, "NOTE opening note")
        self.assertEqual(document.segments[0].identifier, "intro")
        self.assertEqual(document.segments[0].settings, "line:90%")
        self.assertEqual(document.segments[1].settings, "align:start")
        self.assertEqual(rendered, content)

    def test_parse_txt_document_preserves_line_order(self) -> None:
        content = "alpha\n\nbeta\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.txt"
            path.write_text(content, encoding="utf-8")
            document = parse_txt_document(path)

        self.assertEqual(document.format, "txt")
        self.assertEqual(
            [(segment.id, segment.text) for segment in document.segments],
            [("1", "alpha"), ("2", ""), ("3", "beta")],
        )

    def test_parse_srt_document_accepts_missing_indices_and_preserves_settings(self) -> None:
        content = (
            "00:00:01,000 --> 00:00:03,000 X1:10 X2:20 Y1:30 Y2:40\n"
            "<i>Hello</i>\n\n"
            "2\n"
            "00:00:04,000-->00:00:06,000\n"
            "{\\an8}World\n"
        )
        expected_rendered = (
            "1\n"
            "00:00:01,000 --> 00:00:03,000 X1:10 X2:20 Y1:30 Y2:40\n"
            "<i>Hello</i>\n\n"
            "2\n"
            "00:00:04,000 --> 00:00:06,000\n"
            "{\\an8}World\n"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "wild.srt"
            path.write_text(content, encoding="utf-8")

            document = parse_srt_document(path)
            rendered = render_document(document, document.segments, bilingual=False)

        self.assertEqual([segment.id for segment in document.segments], ["1", "2"])
        self.assertIsNone(document.segments[0].identifier)
        self.assertEqual(document.segments[0].settings, "X1:10 X2:20 Y1:30 Y2:40")
        self.assertEqual(document.segments[0].text, "<i>Hello</i>")
        self.assertEqual(document.segments[1].identifier, "2")
        self.assertEqual(document.segments[1].text, "{\\an8}World")
        self.assertEqual(rendered, expected_rendered)
