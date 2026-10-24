"""Config directory + persisted auth/session state.

State lives in an XDG-style config dir (overridable), mirroring how the app
keeps its Curity client + tokens in SharedPreferences:

    {config}/state.json  -> DCR client id/secret + access/refresh tokens

Env overrides:
    ICA_HANDLA_CONFIG_DIR   base config dir (default ~/.config/ica-handla)
    ICA_HANDLA_STATE_PATH   full path to state.json
    ICA_USER / ICA_PASS     credentials for `login` (never persisted as plaintext)
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def config_dir() -> Path:
    override = os.environ.get("ICA_HANDLA_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "ica-handla"


def state_path() -> Path:
    override = os.environ.get("ICA_HANDLA_STATE_PATH")
    if override:
        return Path(override).expanduser()
    return config_dir() / "state.json"


@dataclass
class State:
    # DCR-registered client (per "device")
    client_id: str | None = None
    client_secret: str | None = None
    client_scope: str | None = None
    # OAuth tokens
    access_token: str | None = None
    refresh_token: str | None = None
    token_scope: str | None = None
    expires_at: float | None = None  # epoch seconds
    # saved personnummer (never the password)
    username: str | None = None
    # Handla online-shop web session (separate backend: handlaprivatkund.ica.se)
    handla_cookie: str | None = None
    handla_store_id: str | None = None
    handla_csrf: str | None = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "State":
        p = state_path()
        if not p.exists():
            return cls()
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def save(self) -> None:
        p = state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))
        try:
            p.chmod(0o600)
        except OSError:
            pass

    def clear(self) -> None:
        p = state_path()
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        for f in self.__dataclass_fields__:  # type: ignore[attr-defined]
            setattr(self, f, {} if f == "extra" else None)
