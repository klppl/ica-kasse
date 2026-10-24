#!/usr/bin/env python3
"""Example: log in to ICA, then print your account info and shopping lists.

Run from the repo root (needs `pip install requests`):

    python ica_example.py

Your personnummer and password are prompted for (or taken from ICA_USER /
ICA_PASS). The password is never written to disk; the session tokens are saved
to the same state.json the `ica` CLI uses, so you stay logged in next time.
"""
from __future__ import annotations

import getpass
import logging
import os
import sys

from ica_handla.api import IcaApi
from ica_handla.auth import Authenticator
from ica_handla.config import State
from ica_handla.errors import IcaError


def main() -> int:
    if "-v" in sys.argv[1:]:
        logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    username = os.environ.get("ICA_USER") or input("Personnummer (ÅÅÅÅMMDDXXXX): ").strip()
    password = os.environ.get("ICA_PASS") or getpass.getpass("Lösenord: ")

    auth = Authenticator(State.load())
    api = IcaApi(auth)

    try:
        print("\nLoggar in ...")
        auth.login(username, password)
        print("Inloggad.\n")

        print("=== Konto ===")
        customer = api.customer()
        if isinstance(customer, dict):
            for key, value in customer.items():
                if not isinstance(value, (dict, list)):
                    print(f"  {key}: {value}")
        else:
            print(f"  {customer}")

        print("\n=== Inköpslistor ===")
        lists = api.lists()
        if not lists:
            print("  (inga listor)")
        for sl in lists:
            rows = sl.get("rows") or []
            print(f"\n{sl.get('title')}  ({len(rows)} varor)")
            for row in rows:
                mark = "x" if row.get("isStrikedOver") else " "
                qty = " ".join(str(p) for p in (row.get("quantity"), row.get("unit")) if p)
                print(f"  [{mark}] {row.get('productName')}" + (f"  ({qty})" if qty else ""))
    except IcaError as e:
        print(f"\nFel: {e.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
