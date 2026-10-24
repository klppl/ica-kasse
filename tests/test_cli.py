import json

import pytest

from ica_handla import cli
from ica_handla.config import State


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ICA_HANDLA_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.delenv("ICA_USER", raising=False)
    monkeypatch.delenv("ICA_PASS", raising=False)
    return tmp_path


def test_parser_builds_help():
    with pytest.raises(SystemExit) as e:
        cli.main(["-h"])
    assert e.value.code == 0


def test_authed_command_without_login_errors(capsys):
    rc = cli.main(["whoami"])
    assert rc == 2  # AUTH
    err = json.loads(capsys.readouterr().err.strip())
    assert err["code"] in ("missing_credentials", "auth_failed")


def test_token_import_persists(capsys):
    rc = cli.main(["token", "--refresh-token", "RT123"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out["ok"] is True
    assert State.load().refresh_token == "RT123"


def test_text_format_for_lists(monkeypatch, capsys):
    monkeypatch.setattr("ica_handla.api.IcaApi.lists",
                        lambda self: [{"id": 1, "title": "Hemma", "rows": [{}, {}]}])
    # provide a token so bearer() passes
    cli.main(["token", "--access-token", "AT"])
    capsys.readouterr()
    rc = cli.main(["lists", "ls", "-f", "text"])
    assert rc == 0
    assert "Hemma" in capsys.readouterr().out
