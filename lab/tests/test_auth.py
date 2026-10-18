"""Logging in: what is sent, what is kept, and when a token stops being used."""

from __future__ import annotations

import json
from datetime import date

import pytest

from lab import auth
from lab.auth import AuthError, Credential
from lab.command import HttpError
from lab.command.fake import FakeRunner

URL = "https://secobserve.tail1234.ts.net"
TODAY = date(2026, 10, 18)
PASSWORD = "correct-horse-battery"
CREATE = "/api/authentication/create_user_api_token/"
REVOKE = "/api/authentication/revoke_user_api_token/"


class MemoryStore:
    """A keyring that lives in a dict."""

    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.entries.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.entries[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        del self.entries[(service_name, username)]


def logged_in() -> tuple[FakeRunner, MemoryStore, Credential]:
    so, store = FakeRunner(), MemoryStore()
    so.respond("POST", CREATE, body=json.dumps({"token": "so-minted"}), status=201)
    so.respond("POST", REVOKE, status=204)
    credential = auth.login(so, store, URL, "alvin", PASSWORD, TODAY)
    return so, store, credential


def test_login_replaces_this_machines_token_and_keeps_it() -> None:
    so, store, credential = logged_in()

    revoke, create = so.requests
    # Revoked first: a token name can be minted only once per user.
    assert revoke.url.endswith(REVOKE)
    assert create.url.endswith(CREATE)
    assert create.json is not None
    assert create.json["name"] == revoke.json["name"] == auth.token_name()  # type: ignore[index]
    assert create.json["expiration_date"] == "2027-01-16"
    assert credential == Credential("so-minted", "alvin", URL, date(2027, 1, 16))
    assert auth.stored(store, URL) == credential


def test_the_password_is_never_shown() -> None:
    so, _, _ = logged_in()
    for request in so.requests:
        assert PASSWORD not in request.display()
        error = HttpError(request, 400, f"bad password {PASSWORD}")
        assert PASSWORD not in str(error)


def test_the_environment_overrides_the_keyring() -> None:
    _, store, _ = logged_in()
    env = {auth.ENV: "so-from-ci"}
    assert auth.token(store, URL, env, TODAY) == "so-from-ci"
    assert auth.token(store, URL, {}, TODAY) == "so-minted"


def test_no_token_says_how_to_get_one() -> None:
    with pytest.raises(AuthError, match="lab auth login"):
        auth.token(MemoryStore(), URL, {}, TODAY)


def test_a_token_is_used_through_its_expiry_date_and_not_after() -> None:
    # SecObserve accepts a token on its expiry date.
    _, store, credential = logged_in()
    assert auth.token(store, URL, {}, credential.expires) == "so-minted"
    with pytest.raises(AuthError, match="expired on 2027-01-16"):
        auth.token(store, URL, {}, date(2027, 1, 17))


def test_logout_revokes_then_forgets() -> None:
    so, store, _ = logged_in()
    auth.logout(so, store, URL, PASSWORD)
    assert so.requests[-1].url.endswith(REVOKE)
    assert auth.stored(store, URL) is None


def test_only_a_401_means_the_token_was_rejected() -> None:
    so, _, _ = logged_in()
    request = so.requests[0]
    assert auth.rejected(HttpError(request, 401, "")) is not None
    # A good token lacking a permission.
    assert auth.rejected(HttpError(request, 403, "")) is None
