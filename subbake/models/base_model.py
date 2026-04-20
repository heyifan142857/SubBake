from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from subbake.entities import GlossaryEntry, TranslationLine, Usage


class LLMBackend(ABC):
    @abstractmethod
    def generate_json(self, messages: list[dict[str, str]]) -> tuple[dict, Usage]:
        raise NotImplementedError

    @abstractmethod
    def check_credentials(self) -> tuple[bool, str]:
        raise NotImplementedError


class MockBackend(LLMBackend):
    def generate_json(self, messages: list[dict[str, str]]) -> tuple[dict, Usage]:
        prompt = "\n".join(message["content"] for message in messages)
        task = _extract_between(prompt, "TASK_START", "TASK_END").strip()
        usage = Usage(
            input_tokens=_estimate_tokens(prompt),
            output_tokens=0,
            total_tokens=0,
        )

        if task == "translate_subtitles":
            payload = json.loads(_extract_between(prompt, "BATCH_JSON_START", "BATCH_JSON_END"))
            lines = []
            glossary_updates = []
            for item in payload["lines"]:
                source_text = item["text"]
                translated = "" if not source_text.strip() else f"[MOCK-ZH] {source_text}"
                lines.append({"id": item["id"], "translation": translated})
                names = re.findall(r"\b[A-Z][a-zA-Z]+\b", source_text)
                for name in names:
                    glossary_updates.append({"source": name, "target": name})
            result = {
                "lines": lines,
                "summary": "Mock summary of the latest subtitle batch.",
                "glossary_updates": glossary_updates,
            }
        elif task == "review_translations":
            payload = json.loads(_extract_between(prompt, "REVIEW_JSON_START", "REVIEW_JSON_END"))
            result = {
                "lines": [
                    {"id": item["id"], "translation": item["translation"]}
                    for item in payload["lines"]
                ],
                "review_notes": "Mock review kept translations unchanged.",
            }
        else:
            raise ValueError(f"Unsupported mock task: {task}")

        rendered = json.dumps(result, ensure_ascii=False)
        usage.output_tokens = _estimate_tokens(rendered)
        usage.total_tokens = usage.input_tokens + usage.output_tokens
        return result, usage

    def check_credentials(self) -> tuple[bool, str]:
        return True, "Mock provider does not require an API key."


class OpenAIBackend(LLMBackend):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise ValueError("Missing API key for OpenAI provider. Set OPENAI_API_KEY or use --api-key.")

    def generate_json(self, messages: list[dict[str, str]]) -> tuple[dict, Usage]:
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }

        try:
            return self._request(payload)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 400 and "response_format" in body:
                fallback = {"model": self.model, "messages": messages}
                return self._request(fallback)
            raise RuntimeError(f"OpenAI request failed: {body}") from exc

    def check_credentials(self) -> tuple[bool, str]:
        request = urllib.request.Request(
            url=f"{self.base_url}/models",
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return False, _format_http_error("OpenAI-compatible", exc.code, body)
        except urllib.error.URLError as exc:
            return False, f"OpenAI-compatible credential check failed: {exc.reason}"

        model_count = len(data.get("data", [])) if isinstance(data, dict) else 0
        if model_count:
            return True, f"Credentials look valid. {model_count} model(s) visible from {self.base_url}."
        return True, f"Credentials look valid. Successfully reached {self.base_url}."

    def _request(self, payload: dict) -> tuple[dict, Usage]:
        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        parsed = _extract_json_object(content)
        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("prompt_tokens", _estimate_tokens(json.dumps(payload))),
            output_tokens=usage_data.get("completion_tokens", _estimate_tokens(content)),
            total_tokens=usage_data.get("total_tokens", 0),
        )
        if usage.total_tokens == 0:
            usage.total_tokens = usage.input_tokens + usage.output_tokens
        return parsed, usage


class AnthropicBackend(LLMBackend):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise ValueError("Missing API key for Anthropic provider. Set ANTHROPIC_API_KEY or use --api-key.")

    def generate_json(self, messages: list[dict[str, str]]) -> tuple[dict, Usage]:
        system_parts = [message["content"] for message in messages if message["role"] == "system"]
        body_messages = [
            {"role": message["role"], "content": [{"type": "text", "text": message["content"]}]}
            for message in messages
            if message["role"] != "system"
        ]
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "system": "\n\n".join(system_parts),
            "messages": body_messages,
        }
        request = urllib.request.Request(
            url="https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic request failed: {body}") from exc

        chunks = [
            item.get("text", "")
            for item in data.get("content", [])
            if item.get("type") == "text"
        ]
        text = "\n".join(chunks)
        parsed = _extract_json_object(text)
        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("input_tokens", _estimate_tokens(json.dumps(payload))),
            output_tokens=usage_data.get("output_tokens", _estimate_tokens(text)),
            total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
        )
        if usage.total_tokens == 0:
            usage.total_tokens = usage.input_tokens + usage.output_tokens
        return parsed, usage

    def check_credentials(self) -> tuple[bool, str]:
        request = urllib.request.Request(
            url="https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return False, _format_http_error("Anthropic", exc.code, body)
        except urllib.error.URLError as exc:
            return False, f"Anthropic credential check failed: {exc.reason}"

        model_count = len(data.get("data", [])) if isinstance(data, dict) else 0
        if model_count:
            return True, f"Credentials look valid. {model_count} model(s) visible from Anthropic."
        return True, "Credentials look valid. Successfully reached Anthropic."


def build_backend(
    provider: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 120.0,
) -> LLMBackend:
    normalized = provider.lower()
    if normalized == "mock":
        return MockBackend()
    if normalized in {"openai", "openai-compatible", "compatible"}:
        return OpenAIBackend(
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    if normalized == "anthropic":
        return AnthropicBackend(
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"Unsupported provider: {provider}")


def parse_translation_lines(items: list[dict]) -> list[TranslationLine]:
    return [
        TranslationLine(id=str(item["id"]), translation=str(item["translation"]))
        for item in items
    ]


def parse_glossary_entries(items: list[dict]) -> list[GlossaryEntry]:
    entries: list[GlossaryEntry] = []
    for item in items:
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        if source and target:
            entries.append(GlossaryEntry(source=source, target=target))
    return entries


def _extract_between(text: str, start_marker: str, end_marker: str) -> str:
    start_index = text.index(start_marker) + len(start_marker)
    end_index = text.index(end_marker, start_index)
    return text[start_index:end_index].strip()


def _extract_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, end_index = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
        if end_index:
            break
    raise ValueError(f"Failed to parse JSON object from model output: {text}")


def _estimate_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


def _format_http_error(provider_label: str, status_code: int, body: str) -> str:
    normalized = body.strip().replace("\n", " ")
    if status_code in {401, 403}:
        return f"{provider_label} rejected the credentials ({status_code}): {normalized}"
    return f"{provider_label} credential check failed ({status_code}): {normalized}"
