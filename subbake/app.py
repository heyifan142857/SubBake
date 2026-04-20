from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from subbake.entities import PipelineOptions
from subbake.models import build_backend
from subbake.pipeline import SubtitlePipeline
from subbake.ui import Dashboard

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Translate subtitle files with LLM backends, batch memory, validation, and final review.",
)
console = Console()


@app.callback()
def main() -> None:
    """subbake CLI."""


@app.command()
def translate(
    input_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Input .srt, .vtt, or .txt file."),
    output: Path | None = typer.Option(None, "--output", "-o", dir_okay=False, help="Output file path."),
    provider: str = typer.Option("mock", "--provider", help="LLM provider: mock, openai, anthropic."),
    model: str = typer.Option("mock-zh", "--model", help="Model name for the selected provider."),
    api_key: str | None = typer.Option(None, "--api-key", help="API key override for the provider."),
    base_url: str | None = typer.Option(None, "--base-url", help="OpenAI-compatible API base URL."),
    batch_size: int = typer.Option(50, "--batch-size", min=1, help="Subtitle entries per translation batch."),
    bilingual: bool = typer.Option(False, "--bilingual", help="Emit bilingual subtitles."),
    source_language: str = typer.Option("Auto", "--source-language", help="Source language hint."),
    target_language: str = typer.Option("Chinese", "--target-language", help="Target language."),
    retries: int = typer.Option(2, "--retries", min=0, help="Retries for malformed model output."),
    final_review: bool = typer.Option(True, "--final-review/--no-final-review", help="Run the consistency review pass."),
    timeout: float = typer.Option(120.0, "--timeout", min=1.0, help="Per-request timeout in seconds."),
) -> None:
    """Translate subtitles while preserving subtitle structure."""

    options = PipelineOptions(
        input_path=input_path,
        output_path=output,
        provider=provider,
        model=model,
        batch_size=batch_size,
        bilingual=bilingual,
        source_language=source_language,
        target_language=target_language,
        retries=retries,
        final_review=final_review,
        timeout_seconds=timeout,
        api_key=api_key,
        base_url=base_url,
    )

    try:
        backend = build_backend(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout,
        )
        dashboard = Dashboard(console=console)
        pipeline = SubtitlePipeline(backend=backend, options=options, dashboard=dashboard)
        result = pipeline.run()
    except Exception as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print("")
    console.print(f"[bold green]Output:[/bold green] {result.output_path}")
    console.print(
        "[bold green]Usage:[/bold green] "
        f"{result.usage.input_tokens:,} in / {result.usage.output_tokens:,} out / {result.usage.total_tokens:,} total"
    )
    console.print(
        "[bold green]Batches:[/bold green] "
        f"{result.batches_translated} translated, {result.review_batches} reviewed"
    )


if __name__ == "__main__":
    app()
