from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from subbake import __version__
from subbake.entities import PipelineOptions
from subbake.models import build_backend
from subbake.pipeline import SubtitlePipeline
from subbake.ui import Dashboard

APP_HELP = """LLM subtitle translation CLI with Chinese as the default target language.

Common commands:
  sbake translate input.srt --provider openai
  sbake translate input.vtt --bilingual
  sbake translate input.srt --dry-run

Common options for `sbake translate`:
  --provider       Choose the model provider, such as mock / openai / anthropic
  --model          Set the model name
  --base-url       Set the OpenAI-compatible API base URL
  --api-key        Pass the API key directly
  --batch-size     Batch size, default is 50
  --bilingual      Output bilingual subtitles
  --dry-run        Parse and plan batches without calling the model
  --resume         Resume from run_state.json when available
  --cache          Reuse cached responses for identical prompts
  --work-dir       Directory for cache / run state / failures
  --glossary-path  Path to the persistent glossary JSON file

See full translate command options:
  sbake translate --help
"""

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=APP_HELP,
)
console = Console()


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(f"subbake {__version__}")
    raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
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
    dry_run: bool = typer.Option(False, "--dry-run", help="Only parse and show batch planning without calling the model."),
    resume: bool = typer.Option(True, "--resume/--no-resume", help="Resume from saved run state when available."),
    cache: bool = typer.Option(True, "--cache/--no-cache", help="Reuse cached responses for identical prompts."),
    work_dir: Path | None = typer.Option(None, "--work-dir", file_okay=False, help="Directory for cache, run state, failures, and default glossary."),
    glossary_path: Path | None = typer.Option(None, "--glossary-path", dir_okay=False, help="Persistent glossary JSON path."),
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
        dry_run=dry_run,
        resume=resume,
        use_cache=cache,
        work_dir=work_dir,
        glossary_path=glossary_path,
    )

    try:
        backend = None
        if not dry_run:
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
    if result.dry_run:
        from rich.table import Table

        console.print("[bold yellow]Dry run:[/bold yellow] no model API calls were made.")
        console.print(f"[bold green]Planned batches:[/bold green] {len(result.planned_batches)}")
        if result.planned_batches:
            table = Table(title="Batch Plan")
            table.add_column("Batch", justify="right")
            table.add_column("Lines", justify="right")
            table.add_column("IDs")
            for batch in result.planned_batches:
                table.add_row(
                    str(batch.index),
                    str(batch.size),
                    f"{batch.first_id} -> {batch.last_id}",
                )
            console.print(table)
        if result.glossary_path is not None:
            console.print(f"[bold green]Glossary:[/bold green] {result.glossary_path}")
        if result.state_path is not None:
            console.print(f"[bold green]Run state:[/bold green] {result.state_path}")
        return

    console.print(f"[bold green]Output:[/bold green] {result.output_path}")
    console.print(
        "[bold green]Usage:[/bold green] "
        f"{result.usage.input_tokens:,} in / {result.usage.output_tokens:,} out / {result.usage.total_tokens:,} total"
    )
    console.print(
        "[bold green]Batches:[/bold green] "
        f"{result.batches_translated} translated, {result.review_batches} reviewed"
    )
    if result.cache_hits:
        console.print(f"[bold green]Cache hits:[/bold green] {result.cache_hits}")
    if result.glossary_path is not None:
        console.print(f"[bold green]Glossary:[/bold green] {result.glossary_path}")
    if result.state_path is not None:
        console.print(f"[bold green]Run state:[/bold green] {result.state_path}")


if __name__ == "__main__":
    app()
