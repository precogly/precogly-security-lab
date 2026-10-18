"""Reading this machine's tailnet from the local tailscaled.

Through the `tailscale` CLI, which needs no credentials. The `tailscale` package
on PyPI is a client for the cloud API and would need an API key on the scanner
box, beside untrusted jobs.
"""

from __future__ import annotations

import ipaddress
import json
import shutil
from pathlib import Path

from lab.command.core import Command, CommandError, CommandRunner, Effect

# Tailscale's Mac App Store app ships its CLI inside the bundle, and Tailscale's
# instructions put it on the shell with an alias, which a subprocess never sees
# (tailscale.com/kb/1080).
_MACOS_APP = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
_INSTALL = "install Tailscale: https://tailscale.com/download"


def _tailscale(*args: str) -> Command:
    return Command(
        ("tailscale", *args),
        Effect.READ,
        timeout=15,
        search=(_MACOS_APP,),
        install_hint=_INSTALL,
    )


def location() -> Path | None:
    """Where the live runner will find tailscale, as `lab auth status` shows it."""
    on_path = shutil.which("tailscale")
    if on_path:
        return Path(on_path)
    return _MACOS_APP if _MACOS_APP.is_file() else None


def status() -> Command:
    return _tailscale("status", "--json")


def ip4(host: str) -> Command:
    return _tailscale("ip", "-4", host)


def tailnet_suffix(runner: CommandRunner) -> str:
    """This machine's tailnet DNS suffix, such as "tail1234.ts.net"."""
    command = status()
    suffix = json.loads(runner.run(command).stdout).get("MagicDNSSuffix")
    if not isinstance(suffix, str) or not suffix:
        raise CommandError(
            command, "no MagicDNSSuffix: is MagicDNS on for the tailnet?"
        )
    return suffix


def address(runner: CommandRunner, host: str) -> str:
    """A tailnet host's IPv4 address, as tailscaled resolves it."""
    command = ip4(host)
    text = runner.run(command).stdout.strip()
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError:
        raise CommandError(command, f"not an IPv4 address: {text!r}") from None
