"""Drawing a run's events: a live display on a terminal, plain lines elsewhere.

No scanner reports how far through it is when it has no terminal of its own
(docs/design.md, D14), so a job shows a spinner and the time it has taken, never
a percentage; the only bar counts jobs finished.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TaskID,
    TextColumn,
)
from rich.table import Column
from rich.text import Text

from lab.events import Event


def _when(item: Event) -> datetime:
    return datetime.fromisoformat(item["at"])


def _elapsed(start: datetime, end: datetime) -> str:
    seconds = int((end - start).total_seconds())
    return f"{seconds // 60}m{seconds % 60:02d}s"


def result(item: Event) -> tuple[bool, str]:
    """Whether a finished job succeeded, and its line: `ok · 36 updated`."""
    if item.get("status") == "ok":
        counts = item.get("observations") or {}
        parts = [
            f"{counts[k]} {k}" for k in ("new", "updated", "resolved") if counts.get(k)
        ]
        return True, " · ".join(["ok", *parts]) if parts else "ok · no findings"
    first_line = (item.get("error") or "").strip().splitlines()[:1]
    return False, " · ".join([str(item.get("status")), *first_line])


class _Mark(SpinnerColumn):
    """A spinner while a job runs; then its mark, ✓ or ✗."""

    def render(self, task: Task) -> Any:
        if task.finished:
            return Text(task.fields.get("mark", ""))
        return super().render(task)


class _OverallOnly(ProgressColumn):
    """A column drawn on the jobs-finished row only: a job has no fraction."""

    def __init__(self, column: ProgressColumn) -> None:
        super().__init__()
        self._column = column

    def render(self, task: Task) -> Any:
        return self._column.render(task) if task.fields.get("overall") else Text("")


class _Elapsed(ProgressColumn):
    """Time since the job's own start event, so a reattach shows true times."""

    def render(self, task: Task) -> Text:
        started: datetime | None = task.fields.get("started")
        if started is None:
            return Text("")
        ended: datetime = task.fields.get("ended") or datetime.now(UTC)
        return Text(_elapsed(started, ended), style="progress.elapsed")


class Display:
    """Shows each event as it comes; `close` when the run is over."""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._live: Progress | None = None
        self._jobs: dict[str, TaskID] = {}
        self._started: dict[str, datetime] = {}
        self._overall: TaskID | None = None
        if console.is_terminal:
            self._live = Progress(
                _Mark(),
                # Fixed, so a result appearing does not shift the columns after it.
                TextColumn(
                    "{task.description}",
                    table_column=Column(width=48, no_wrap=True, overflow="ellipsis"),
                ),
                _OverallOnly(BarColumn(bar_width=20)),
                _OverallOnly(MofNCompleteColumn()),
                _Elapsed(),
                console=console,
            )
            self._live.start()

    def handle(self, item: Event) -> None:
        kind = item.get("type")
        if kind == "version":
            self._say(f"scanner box: lab at {str(item.get('lab'))[:12]}")
        elif kind == "run":
            jobs = item.get("jobs") or []
            self._say(
                f"run {item.get('run')}, Precogly at {str(item.get('precogly'))[:7]}"
            )
            if self._live:
                self._overall = self._live.add_task(
                    "jobs", total=len(jobs), mark="✓", started=_when(item), overall=True
                )
        elif kind == "job_started":
            job = str(item.get("job"))
            self._started[job] = _when(item)
            if self._live:
                self._jobs[job] = self._live.add_task(
                    job, total=None, started=_when(item)
                )
            else:
                self._say(f"  started  {job}")
        elif kind == "job_finished":
            self._finish_job(item)
        elif kind == "run_finished" and self._live and self._overall is not None:
            self._live.update(self._overall, ended=_when(item))
        # "failed" is not drawn: the caller reports it as the run's error.

    def _finish_job(self, item: Event) -> None:
        job = str(item.get("job"))
        ok, line = result(item)
        mark = "[green]✓[/]" if ok else "[red]✗[/]"
        started = self._started.get(job, _when(item))
        took = _elapsed(started, _when(item))
        if self._live:
            task = self._jobs.get(job)
            if task is not None:
                self._live.update(
                    task,
                    description=f"{job:<16} {line}",
                    total=1,
                    completed=1,
                    mark="✓" if ok else "✗",
                    ended=_when(item),
                )
            if self._overall is not None:
                self._live.advance(self._overall)
        else:
            self._console.print(f"  {mark} {job:<16} {line} ({took})")

    def _say(self, text: str) -> None:
        if self._live:
            self._live.console.print(text)
        else:
            self._console.print(text)

    def close(self) -> None:
        if self._live:
            self._live.stop()
