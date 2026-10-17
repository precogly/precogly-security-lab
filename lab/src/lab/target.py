"""Targets: one TOML file per Precogly deployment that jobs run against."""

from __future__ import annotations

import json
import string
import subprocess
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class TargetError(ValueError):
    """A target definition that cannot be used."""


@dataclass(frozen=True)
class Login:
    email: str
    password: str
    organization: str
    role: str


@dataclass(frozen=True)
class Target:
    name: str
    # Holds `{tailnet}`, the tailnet's MagicDNS suffix, which differs per
    # deployment and so is never written into the repository.
    url_template: str
    logins: tuple[Login, ...]

    def url(self, tailnet: str) -> str:
        return self.url_template.format(tailnet=tailnet)

    def host(self, tailnet: str) -> str:
        host = urlsplit(self.url(tailnet)).hostname
        assert host, "a validated url always has a host"
        return host

    def as_json(self, tailnet: str) -> str:
        """What a job reads at /run/lab/target.json."""
        logins = [asdict(login) for login in self.logins]
        return json.dumps({"url": self.url(tailnet), "logins": logins}, indent=2)


def load_target(path: Path) -> Target:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    try:
        return _parse(raw, path.stem)
    except TargetError as err:
        raise TargetError(f"{path}: {err}") from None


def tailnet_suffix() -> str:
    """This machine's tailnet DNS suffix, such as "tail1234.ts.net".

    Read from the local daemon, which needs no credentials. The `tailscale`
    package on PyPI is a client for the cloud API and would need an API key on
    the scanner box, beside untrusted jobs.
    """
    try:
        out = subprocess.run(
            ["tailscale", "status", "--json"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as err:
        msg = "cannot read the tailnet suffix: is Tailscale installed and up?"
        raise TargetError(msg) from err
    suffix = json.loads(out).get("MagicDNSSuffix")
    if not isinstance(suffix, str) or not suffix:
        raise TargetError("tailscale status has no MagicDNSSuffix: is MagicDNS on?")
    return suffix


_LOGIN_FIELDS = frozenset({"email", "password", "organization", "role"})


def _parse(raw: dict[str, Any], stem: str) -> Target:
    if unknown := set(raw) - {"name", "url", "logins"}:
        raise TargetError(f"unknown keys {sorted(unknown)}")

    name = raw.get("name")
    if name != stem:
        raise TargetError(f"name {name!r} must match the file name {stem!r}")

    url = raw.get("url")
    if not isinstance(url, str):
        raise TargetError("url must be a string")
    used = {f for _, f, _, _ in string.Formatter().parse(url) if f is not None}
    if unknown_fields := used - {"tailnet"}:
        raise TargetError(f"url uses {sorted(unknown_fields)}; only {{tailnet}}")
    parts = urlsplit(url.format(tailnet="example.ts.net"))
    if parts.scheme != "https" or not parts.hostname:
        raise TargetError(f"url {url!r} must be https:// with a host")

    logins = raw.get("logins")
    if not isinstance(logins, list) or not logins:
        raise TargetError("logins must be a non-empty list")
    for login in logins:
        if not isinstance(login, dict) or set(login) != _LOGIN_FIELDS:
            raise TargetError(f"each login needs exactly {sorted(_LOGIN_FIELDS)}")
        if not all(isinstance(v, str) and v for v in login.values()):
            raise TargetError("login fields must be non-empty strings")

    return Target(
        name=name,
        url_template=url,
        logins=tuple(Login(**login) for login in logins),
    )
