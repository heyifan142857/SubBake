from __future__ import annotations

from dataclasses import dataclass, field

from subbake.entities import GlossaryEntry


DEFAULT_STYLE_RULES = [
    "Use natural, idiomatic Chinese.",
    "Preserve tone, humor, emotion, and profanity where present.",
    "Keep subtitles concise and easy to read on screen.",
    "Do not merge or drop subtitle entries.",
]


@dataclass(slots=True)
class ContextMemory:
    style_rules: list[str] = field(default_factory=lambda: list(DEFAULT_STYLE_RULES))
    recent_summaries: list[str] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    max_summaries: int = 2

    def snapshot(self) -> dict:
        return {
            "recent_summaries": self.recent_summaries[-self.max_summaries :],
            "glossary": self.glossary,
            "style_rules": self.style_rules,
        }

    def update(self, summary: str, glossary_updates: list[GlossaryEntry]) -> None:
        clean_summary = summary.strip()
        if clean_summary:
            self.recent_summaries.append(clean_summary)
            self.recent_summaries = self.recent_summaries[-self.max_summaries :]
        for entry in glossary_updates:
            self.glossary[entry.source] = entry.target
