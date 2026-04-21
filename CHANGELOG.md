# Changelog

This file tracks the current unreleased working tree changes.

## Unreleased

### Added

- Incremental checkpoint storage with lightweight `run_state.json` plus per-batch shards under `translated_batches/` and `reviewed_batches/`.
- Cross-file translation memory persisted to `.subbake/translation_memory.json`.
- Split `translation_fingerprint` and `render_fingerprint` so bilingual rendering changes can reuse finished translations.
- Provider-side retry handling for OpenAI-compatible and Anthropic requests with exponential backoff, `Retry-After`, request ids, and structured failure metadata.
- Dashboard ETA estimation that updates during translation and review batches.
- Regression tests for incremental resume, render reuse, translation memory reuse, provider parsing behavior, prompt shaping, dashboard ETA, adaptive batching, and structural split retries.
- This changelog to summarize the current uncommitted work.

### Changed

- Default `--batch-size` is now `30`, which is a better quality-throughput balance for subtitle translation than the previous default of `50`.
- Translation prompts now use compact JSON payloads, omit timestamps, and more strongly forbid merging subtitle entries even when one spoken sentence spans multiple subtitle lines.
- Final review is now targeted at high-risk batches instead of replaying every batch.
- Translation batching is now adaptive: it considers character load, estimated tokens, semantic boundaries, split-sentence risk, speaker changes, and formatting risk instead of only a fixed entry count.
- Structural validation failures during translation now trigger automatic sub-batch retries before the batch is marked failed.
- Translation failure messages now explain likely causes such as missing or merged lines, empty translations, rate limits, and transport failures, and suggest retry guidance such as lowering `--batch-size`.
- CLI help and README wording now describe targeted review, intelligent batching, and incremental runtime artifacts more accurately.

### Fixed

- OpenAI-compatible responses that use `text` or `target` instead of `translation` are now accepted when parsing translation lines.
- Glossary updates are accepted both as a list of entries and as a plain source-to-target mapping.
- Existing translations can now be reused when only the render mode changes, such as switching to bilingual output.
- Project metadata now advertises Python `3.14` support in package classifiers.

### Docs

- README now documents incremental batch shard outputs and clarifies that final review only runs on high-risk batches.
