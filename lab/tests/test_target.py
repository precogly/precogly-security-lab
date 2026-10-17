"""Targets: the shipped pentest target, and what each rule rejects."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

from lab.target import TargetError, load_target

SHIPPED = Path(str(files("lab") / "targets" / "pentest.toml"))

VALID = """
name = "pentest"
url  = "https://pentest.{tailnet}"

[[logins]]
email        = "admin@precogly.dev"
password     = "admin123"
organization = "Demo Organization"
role         = "security_team"
"""


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pentest.toml"
    path.write_text(body)
    return path


def test_shipped_target_has_two_tenants() -> None:
    # The cross-tenant harness needs logins in at least two organizations.
    target = load_target(SHIPPED)
    assert len({login.organization for login in target.logins}) >= 2


def test_url_and_target_json_fill_the_tailnet(tmp_path: Path) -> None:
    target = load_target(write(tmp_path, VALID))
    assert target.url("tail1234.ts.net") == "https://pentest.tail1234.ts.net"
    assert target.host("tail1234.ts.net") == "pentest.tail1234.ts.net"
    doc = json.loads(target.as_json("tail1234.ts.net"))
    assert doc["url"] == "https://pentest.tail1234.ts.net"
    assert doc["logins"][0]["organization"] == "Demo Organization"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("https://", "http://"), "must be https://"),
        (("{tailnet}", "{domain}"), "only {tailnet}"),
        (('name = "pentest"', 'name = "prod"'), "must match the file name"),
        (('role         = "security_team"\n', ""), "each login needs exactly"),
    ],
)
def test_rejects(tmp_path: Path, change: tuple[str, str], message: str) -> None:
    with pytest.raises(
        TargetError, match=message.replace("{", r"\{").replace("}", r"\}")
    ):
        load_target(write(tmp_path, VALID.replace(*change)))
