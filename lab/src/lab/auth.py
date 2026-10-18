"""Logging in to SecObserve: one token per machine, kept in the system keyring."""

from __future__ import annotations

import json
import socket
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Protocol

from lab.command import CommandRunner, HttpError
from lab.command import secobserve as api

# Overrides the keyring, for CI and for machines with no keyring.
ENV = "SECOBSERVE_TOKEN"
# The keyring service lab's entries are filed under, one per SecObserve URL.
SERVICE = "lab"
# How long a minted token lasts; see docs/design.md for the trade.
LIFETIME = timedelta(days=90)

LOGIN = "Run: lab auth login"


class AuthError(ValueError):
    """No usable token, and what to do about it."""


class SecretStore(Protocol):
    """The part of `keyring` lab uses; the module itself satisfies it."""

    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


@dataclass(frozen=True)
class Credential:
    token: str
    user: str
    url: str
    expires: date


def token_name() -> str:
    """`lab-<host>`: SecObserve token names are unique per user, so one per machine."""
    return f"lab-{socket.gethostname().split('.')[0]}"


def _save(store: SecretStore, credential: Credential) -> None:
    record = {**asdict(credential), "expires": credential.expires.isoformat()}
    store.set_password(SERVICE, credential.url, json.dumps(record))


def stored(store: SecretStore, url: str) -> Credential | None:
    raw = store.get_password(SERVICE, url)
    if raw is None:
        return None
    try:
        record = json.loads(raw)
        return Credential(
            token=record["token"],
            user=record["user"],
            url=record["url"],
            expires=date.fromisoformat(record["expires"]),
        )
    except (ValueError, KeyError, TypeError):
        raise AuthError(f"the keyring entry for {url} is unreadable. {LOGIN}") from None


def login(
    runner: CommandRunner,
    store: SecretStore,
    url: str,
    user: str,
    password: str,
    today: date,
) -> Credential:
    """Mint this machine's token, replacing any earlier one, and store it."""
    name = token_name()
    # A name can be minted once; revoking first lets a second login succeed.
    api.revoke_token(runner, url, user, password, name)
    expires = today + LIFETIME
    token = api.create_token(runner, url, user, password, name, expires)
    credential = Credential(token=token, user=user, url=url, expires=expires)
    _save(store, credential)
    return credential


def logout(
    runner: CommandRunner, store: SecretStore, url: str, password: str
) -> Credential:
    """Revoke this machine's token in SecObserve, then forget it."""
    credential = stored(store, url)
    if credential is None:
        raise AuthError(f"not logged in to {url}")
    api.revoke_token(runner, url, credential.user, password, token_name())
    store.delete_password(SERVICE, url)
    return credential


def token(store: SecretStore, url: str, env: Mapping[str, str], today: date) -> str:
    """The token to use: the environment's, else the keyring's if unexpired."""
    if from_env := env.get(ENV):
        return from_env
    credential = stored(store, url)
    if credential is None:
        raise AuthError(f"not logged in to {url}. {LOGIN} (or set {ENV})")
    # SecObserve accepts a token on its expiry date, and so does this.
    if credential.expires < today:
        raise AuthError(f"the token expired on {credential.expires}. {LOGIN}")
    return credential.token


def rejected(err: HttpError) -> AuthError | None:
    """The error to show for a request SecObserve refused for its token.

    Only 401: SecObserve's token authentication answers a bad, expired or
    deactivated token with it, and 403 means a good token lacking a permission.
    """
    if err.status == 401:
        return AuthError(f"SecObserve rejected the token (expired or revoked). {LOGIN}")
    return None
