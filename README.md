# subbake

`subbake` is a Python CLI for translating subtitle files with LLM backends.

## Features

- `.srt`, `.vtt`, and line-based `.txt` input
- batch translation with retry-based validation
- context memory with recent summaries and glossary tracking
- final review pass for consistency
- Rich-powered terminal dashboard

## Quickstart

```bash
pip install -e .
sbake translate episode.srt --provider mock --bilingual
```
