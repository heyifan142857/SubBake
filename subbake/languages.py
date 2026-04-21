from __future__ import annotations

import re

DEFAULT_SOURCE_LANGUAGE = "Auto"
DEFAULT_TARGET_LANGUAGE = "Chinese"

_LANGUAGE_ALIASES = {
    "auto": DEFAULT_SOURCE_LANGUAGE,
    "automatic": DEFAULT_SOURCE_LANGUAGE,
    "detect": DEFAULT_SOURCE_LANGUAGE,
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "zh-hans": "Chinese",
    "cn": "Chinese",
    "chinese": "Chinese",
    "mandarin": "Chinese",
    "zh-tw": "Traditional Chinese",
    "zh-hant": "Traditional Chinese",
    "traditional chinese": "Traditional Chinese",
    "en": "English",
    "english": "English",
    "ja": "Japanese",
    "jp": "Japanese",
    "japanese": "Japanese",
    "ko": "Korean",
    "kr": "Korean",
    "korean": "Korean",
    "fr": "French",
    "french": "French",
    "de": "German",
    "german": "German",
    "es": "Spanish",
    "spanish": "Spanish",
    "pt": "Portuguese",
    "portuguese": "Portuguese",
    "pt-br": "Brazilian Portuguese",
    "pt_br": "Brazilian Portuguese",
    "brazilian portuguese": "Brazilian Portuguese",
    "ru": "Russian",
    "russian": "Russian",
    "it": "Italian",
    "italian": "Italian",
    "ar": "Arabic",
    "arabic": "Arabic",
    "hi": "Hindi",
    "hindi": "Hindi",
}

_LANGUAGE_CODES = {
    DEFAULT_SOURCE_LANGUAGE: "AUTO",
    "Chinese": "ZH",
    "Traditional Chinese": "ZH-TW",
    "English": "EN",
    "Japanese": "JA",
    "Korean": "KO",
    "French": "FR",
    "German": "DE",
    "Spanish": "ES",
    "Portuguese": "PT",
    "Brazilian Portuguese": "PT-BR",
    "Russian": "RU",
    "Italian": "IT",
    "Arabic": "AR",
    "Hindi": "HI",
}


def normalize_language_name(value: str, *, allow_auto: bool = False) -> str:
    stripped = value.strip()
    if not stripped:
        return DEFAULT_SOURCE_LANGUAGE if allow_auto else DEFAULT_TARGET_LANGUAGE

    normalized_key = _normalize_language_key(stripped)
    alias = _LANGUAGE_ALIASES.get(normalized_key)
    if alias == DEFAULT_SOURCE_LANGUAGE and not allow_auto:
        return DEFAULT_TARGET_LANGUAGE
    if alias is not None:
        return alias
    return _beautify_language_name(stripped)


def language_short_code(value: str) -> str:
    language = normalize_language_name(value, allow_auto=True)
    code = _LANGUAGE_CODES.get(language)
    if code is not None:
        return code
    return _slugify(language).upper()


def language_pair_slug(source_language: str, target_language: str) -> str:
    source = normalize_language_name(source_language, allow_auto=True)
    target = normalize_language_name(target_language)
    return f"{_slugify(source)}-to-{_slugify(target)}"


def _normalize_language_key(value: str) -> str:
    compact = value.strip().casefold().replace("_", "-")
    compact = re.sub(r"\s+", " ", compact)
    return compact


def _beautify_language_name(value: str) -> str:
    parts = re.split(r"([\s/-]+)", value.strip())
    return "".join(
        part if re.fullmatch(r"[\s/-]+", part) else part[:1].upper() + part[1:]
        for part in parts
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "language"
