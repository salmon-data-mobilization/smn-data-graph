"""Point the Agent SDK at the Console API key kept in the macOS Keychain.

The key lives in the Keychain item `anthropic-salmon-corpus` (account: $USER),
so it is never written to a file or printed. Usage on this key draws on the
monthly promotional API credit of "Brett's Individual Org", not on a Claude
subscription.
"""

import os
import subprocess

KEYCHAIN_SERVICE = "anthropic-salmon-corpus"

# The SDK passes the whole parent environment to the Claude Code process it
# starts. When a script runs inside a Claude session (desktop app, CLI), that
# environment carries the session's own connection settings, for example
# ANTHROPIC_BASE_URL or an OAuth token. Any of them could route the run through
# the session's account instead of this API key, so drop them all.
_SESSION_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_")
_SESSION_NAMES = ("CLAUDECODE",)


def use_api_key_from_keychain() -> None:
    """Clear inherited Claude session settings and set ANTHROPIC_API_KEY."""
    for name in list(os.environ):
        if name.startswith(_SESSION_PREFIXES) or name in _SESSION_NAMES:
            del os.environ[name]

    found = subprocess.run(
        ["security", "find-generic-password",
         "-a", os.environ["USER"], "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True,
    )
    key = found.stdout.strip()
    if found.returncode != 0 or not key:
        raise SystemExit(
            f"No API key in the Keychain item '{KEYCHAIN_SERVICE}'. Add it with:\n"
            f'  security add-generic-password -a "$USER" -s {KEYCHAIN_SERVICE} -w'
        )
    os.environ["ANTHROPIC_API_KEY"] = key
