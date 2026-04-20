from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from subbake.entities import Usage


@dataclass(slots=True)
class BatchSnapshot:
    index: int = 0
    total: int = 0
    latency_seconds: float = 0.0
    stage_label: str = "IDLE"


class Dashboard:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.usage = Usage()
        self.batch = BatchSnapshot()
        self.total_steps = 1
        self.completed_steps = 0
        self.stage_order = [
            "LOAD_FILE",
            "PARSE",
            "TRANSLATE_BATCH",
            "VALIDATE",
            "FINAL_REVIEW",
            "WRITE_OUTPUT",
        ]
        self.stage_states = {stage: "pending" for stage in self.stage_order}
        self.spinner_frames = ["·  ", "·· ", "···", " ··", "  ·", " ··"]
        self.live = Live(self, console=self.console, refresh_per_second=8)

    @contextmanager
    def running(self):
        with self.live:
            self.refresh()
            yield self

    def set_total_steps(self, total_steps: int) -> None:
        self.total_steps = max(1, total_steps)
        self.refresh()

    def mark_running(self, stage: str, label: str | None = None) -> None:
        for key, value in list(self.stage_states.items()):
            if value == "running":
                self.stage_states[key] = "pending"
        self.stage_states[stage] = "running"
        if label:
            self.batch.stage_label = label
        self.refresh()

    def mark_done(self, stage: str, advance: bool = True) -> None:
        self.stage_states[stage] = "done"
        if advance:
            self.completed_steps += 1
        self.refresh()

    def add_usage(self, usage: Usage) -> None:
        self.usage.add(usage)
        self.refresh()

    def restore_usage(self, usage: Usage) -> None:
        self.usage = Usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
        )
        self.refresh()

    def restore_progress(self, completed_steps: int) -> None:
        self.completed_steps = max(0, completed_steps)
        self.refresh()

    def set_batch(self, index: int, total: int, latency_seconds: float, stage_label: str) -> None:
        self.batch = BatchSnapshot(
            index=index,
            total=total,
            latency_seconds=latency_seconds,
            stage_label=stage_label,
        )
        self.refresh()

    def clear_batch(self) -> None:
        self.batch = BatchSnapshot()
        self.refresh()

    def refresh(self) -> None:
        self.live.refresh()

    def __rich__(self) -> Panel:
        return self.render()

    def render(self) -> Panel:
        timeline_rows: list[Text] = []
        for stage in self.stage_order[:-1]:
            state = self.stage_states[stage]
            label = stage
            if stage == "TRANSLATE_BATCH" and self.batch.total:
                label = f"{stage} {self.batch.index}/{self.batch.total}"
            if stage == "FINAL_REVIEW" and self.batch.stage_label.startswith("FINAL_REVIEW"):
                label = self.batch.stage_label
            style, icon = self._timeline_indicator(state)
            row = Text()
            row.append("[", style=style)
            row.append(icon, style=style)
            row.append("] ", style=style)
            row.append(label)
            timeline_rows.append(row)

        stats = Table.grid(padding=(0, 2))
        stats.add_column(justify="left")
        stats.add_column(justify="right")
        stats.add_row("Progress", self._progress_bar())
        stats.add_row("Input tokens", f"{self.usage.input_tokens:,}")
        stats.add_row("Output tokens", f"{self.usage.output_tokens:,}")
        stats.add_row("Total tokens", f"{self.usage.total_tokens:,}")

        batch_table = Table.grid(padding=(0, 2))
        batch_table.add_column(justify="left")
        batch_table.add_column(justify="right")
        batch_label = (
            f"{self.batch.index}/{self.batch.total}" if self.batch.total else "-"
        )
        batch_table.add_row("Current batch", batch_label)
        batch_table.add_row("Latency", f"{self.batch.latency_seconds:.2f}s" if self.batch.total else "-")

        group = Group(
            Text("subbake", style="bold cyan"),
            Text(""),
            Text("Timeline", style="bold"),
            *timeline_rows,
            Text("Usage", style="bold"),
            stats,
            Text("Current batch", style="bold"),
            batch_table,
        )
        return Panel(group, border_style="cyan", title="Subtitle Translation")

    def _progress_bar(self, width: int = 20) -> str:
        ratio = min(1.0, self.completed_steps / self.total_steps)
        filled = int(ratio * width)
        return f"[{'█' * filled}{'-' * (width - filled)}] {ratio * 100:>5.1f}%"

    def _timeline_indicator(self, state: str) -> tuple[str, str]:
        if state == "done":
            return "green", " ✓ "
        if state == "running":
            frame_index = int(monotonic() * 8) % len(self.spinner_frames)
            return "yellow", self.spinner_frames[frame_index]
        return "white", "   "
