"""Reading this machine's tailnet from the local tailscaled.

Through the `tailscale` CLI, which needs no credentials. The `tailscale` package
on PyPI is a client for the cloud API and would need an API key on the scanner
box, beside untrusted jobs.
"""

from __future__ import annotations

import ipaddress
import json

from lab.command.core import Command, CommandError, CommandRunner, Effect


def status() -> Command:
    return Command(("tailscale", "status", "--json"), Effect.READ, timeout=15)


def ip4(host: str) -> Command:
    return Command(("tailscale", "ip", "-4", host), Effect.READ, timeout=15)


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
