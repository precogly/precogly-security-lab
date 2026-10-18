"""An HTTP request lab sends, and its response."""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from lab.command.core.effect import Effect


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    effect: Effect
    # Pairs, since a filter may repeat (`current_status=Open&current_status=...`).
    query: tuple[tuple[str, str], ...] = ()
    # Every header here is secret: shown as <redacted> wherever a request is
    # printed, and its value removed from error text.
    headers: Mapping[str, str] = field(default_factory=dict)
    # A multipart form, sent when `form` or `file` is set.
    form: Mapping[str, str] = field(default_factory=dict)
    # (field name, path) of a file sent in the form.
    file: tuple[str, Path] | None = None
    timeout: float = 60
    # What a dry run assumes the response was, as for `Command.dry_run`.
    dry_run: HttpResponse | None = None

    def full_url(self) -> str:
        return f"{self.url}?{urlencode(self.query)}" if self.query else self.url

    def display(self) -> str:
        parts = [self.method, self.full_url()]
        parts += [f"{name}: <redacted>" for name in sorted(self.headers)]
        parts += [f"{key}={value}" for key, value in self.form.items()]
        if self.file:
            parts.append(f"{self.file[0]}=@{self.file[1]}")
        return shlex.join(parts)

    def redact(self, text: str) -> str:
        for value in self.headers.values():
            text = text.replace(value, "<redacted>")
        return text
