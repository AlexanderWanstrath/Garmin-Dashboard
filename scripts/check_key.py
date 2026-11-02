"""Diagnose a failing Personal API key without ever printing the key.

Prints the shape of the stored key (length, character classes, line count)
and the error message returned by the token endpoint, with the key redacted.

Usage:
    python scripts/check_key.py
"""

from __future__ import annotations

import string

from garmin_personal_api import (
    DEFAULT_API_KEY_FILE,
    GarminPersonalApiError,
    HttpError,
    PersonalApiAuthenticator,
    resolve_api_key,
)


def describe_shape(raw: str) -> None:
    key = raw.strip()
    allowed = set(string.ascii_letters + string.digits + "-_.=+/")
    print(f"length (raw / stripped): {len(raw)} / {len(key)}")
    print(f"lines: {len(raw.splitlines())}")
    print(f"letters: {sum(c.isalpha() for c in key)}, digits: {sum(c.isdigit() for c in key)}")
    print(f"whitespace inside key: {sum(c.isspace() for c in key)}")
    quotes = sum(c in "\"'" for c in key)
    print(f"quotes: {quotes}, question marks: {key.count('?')}, colons: {key.count(':')}")
    print(f"other unusual characters: {sum(c not in allowed and c not in ':?"\'' and not c.isspace() for c in key)}")


def main() -> None:
    path = DEFAULT_API_KEY_FILE.expanduser()
    if path.exists():
        print(f"key file found ({path.name})")
        describe_shape(path.read_text(encoding="utf-8", errors="replace"))
    else:
        print("no key file, falling back to GARMIN_PERSONAL_API_KEY")

    try:
        key = resolve_api_key()
    except GarminPersonalApiError as exc:
        print(f"key lookup failed: {exc}")
        return
    try:
        with PersonalApiAuthenticator() as authenticator:
            authenticator.obtain_token(key, force_refresh=True)
    except HttpError as exc:
        message = exc.response_text.replace(key, "<KEY>").strip()[:500]
        print(f"token request: HTTP {exc.status_code}")
        print(f"Garmin says: {message or '(empty body)'}")
        return
    print("token request: OK, the key works")


if __name__ == "__main__":
    main()
