"""Unofficial ICA Handla API client + CLI.

Reverse-engineered from se.ica.handla 4.79.1. Not affiliated with ICA.
"""
from __future__ import annotations

__version__ = "0.1.0"

from .api import IcaApi
from .auth import Authenticator
from .config import State

__all__ = ["IcaApi", "Authenticator", "State", "__version__"]
