"""Run one corpus-building agent for one dataset, paid by the API credit.

Usage:
    uv run run_agent.py psf-nuseds-cleaned --budget 9

The agent gets prompts/common.md plus prompts/<dataset>.md. It runs in a
macOS sandbox: shell commands can write only inside this project and reach
only the hosts in ALLOWED_HOSTS, and file-tool writes outside the project are
denied by a hook. Each run writes runs/<run-id>/ with a progress log, a full
transcript (git-ignored) and run.json (cost, tokens, time).
"""

import argparse
import asyncio
import dataclasses
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from corpus_auth import use_api_key_from_keychain

PROJECT = Path(__file__).resolve().parent
MODEL = "claude-opus-5-5"

# Hosts the sandboxed shell may reach: the data sources, the ontology and
# vocabulary services metasalmonpy uses, and GitHub for reference files.
ALLOWED_HOSTS = [
    "zenodo.org",
    "doi.org",
    "w3id.org",
    "purl.org",
    "www.w3.org",
    "qudt.org",
    "www.qudt.org",
    "vocab.nerc.ac.uk",
    "vocab.ices.dk",
    "www.ebi.ac.uk",
    "rs.tdwg.org",
    "api.gbif.org",
    "www.marinespecies.org",
    "salmon-data-mobilization.github.io",
    "dfo-pacific-science.github.io",  # where w3id.org/gcdfo redirects
    "creativecommons.org",
    "github.com",
    "api.github.com",
    "codeload.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
]


async def keep_writes_in_project(input_data, tool_use_id, context):
    """Deny Write/Edit/NotebookEdit calls whose target is outside PROJECT."""
    tool_input = input_data.get("tool_input", {})
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if target and not (PROJECT / target).resolve().is_relative_to(PROJECT):
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Writes are limited to {PROJECT}.",
            }
        }
    return {}


def build_prompt(dataset: str, budget: float) -> str:
    common = (PROJECT / "prompts" / "common.md").read_text()
    task = (PROJECT / "prompts" / f"{dataset}.md").read_text()
    return (
        common.replace("{BUDGET_USD}", f"{budget:.2f}").replace("{PROJECT}", str(PROJECT))
        + "\n\n"
        + task.replace("{PROJECT}", str(PROJECT))
    )


def point_caches_into_project() -> None:
    # The sandbox blocks writes outside the project, so tools that cache in
    # the home directory (uv, matplotlib, HTTP clients) must cache here.
    cache = PROJECT / ".cache"
    (cache / "tmp").mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CACHE_HOME"] = str(cache)
    os.environ["UV_CACHE_DIR"] = str(cache / "uv")
    os.environ["TMPDIR"] = str(cache / "tmp")


def describe(block: ToolUseBlock) -> str:
    detail = block.input.get("command") or block.input.get("file_path") or block.input.get("url") or ""
    return f"[{block.name}] {str(detail).splitlines()[0][:160] if detail else ''}"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dataset", help="slug matching prompts/<dataset>.md")
    parser.add_argument("--budget", type=float, required=True, help="USD limit for this run")
    parser.add_argument("--max-turns", type=int, default=250)
    args = parser.parse_args()

    use_api_key_from_keychain()
    point_caches_into_project()

    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{args.dataset}"
    run_dir = PROJECT / "runs" / run_id
    run_dir.mkdir(parents=True)

    options = ClaudeAgentOptions(
        model=MODEL,
        effort="high",
        cwd=PROJECT,
        allowed_tools=["Read", "Glob", "Grep", "Write", "Edit", "MultiEdit",
                       "Bash", "WebFetch", "WebSearch", "TodoWrite"],
        # No sub-agents (cost control) and no commits; Brett reviews first.
        disallowed_tools=["Task", "Agent", "Bash(git commit:*)", "Bash(git push:*)"],
        permission_mode="dontAsk",
        setting_sources=[],
        sandbox={
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "network": {"allowedDomains": ALLOWED_HOSTS},
        },
        hooks={"PreToolUse": [HookMatcher(matcher="Write|Edit|MultiEdit|NotebookEdit",
                                          hooks=[keep_writes_in_project])]},
        max_turns=args.max_turns,
        max_budget_usd=args.budget,
    )

    clock = time.monotonic()
    progress = open(run_dir / "progress.log", "w")

    def log(line: str) -> None:
        print(line, flush=True)
        progress.write(line + "\n")
        progress.flush()

    log(f"run {run_id}: model {MODEL}, budget ${args.budget:.2f}")
    with open(run_dir / "transcript.jsonl", "w") as transcript:
        async for message in query(prompt=build_prompt(args.dataset, args.budget), options=options):
            record = (dataclasses.asdict(message) if dataclasses.is_dataclass(message)
                      else {"repr": repr(message)})
            transcript.write(json.dumps({"type": type(message).__name__, **record}, default=str) + "\n")
            transcript.flush()
            minutes = (time.monotonic() - clock) / 60
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        log(f"{minutes:6.1f}m  {block.text.strip()[:300]}")
                    elif isinstance(block, ToolUseBlock):
                        log(f"{minutes:6.1f}m  {describe(block)}")
            elif isinstance(message, ResultMessage) and message.origin is None:
                # The result of the task prompt itself. Stop here: later turns
                # (started when a background command finishes) run after the
                # SDK has stopped answering hooks, so their file edits are
                # refused with a "user doesn't want this" message.
                record = {
                    "run_id": run_id,
                    "dataset": args.dataset,
                    "model": MODEL,
                    "budget_usd": args.budget,
                    "started_utc": started.isoformat(),
                    "ended_utc": datetime.now(timezone.utc).isoformat(),
                    "subtype": message.subtype,
                    "is_error": message.is_error,
                    "terminal_reason": message.terminal_reason,
                    "num_turns": message.num_turns,
                    "duration_s": round(message.duration_ms / 1000),
                    "estimated_cost_usd": message.total_cost_usd,
                    "usage": message.usage,
                    "model_usage": message.model_usage,
                    "errors": message.errors,
                    "session_id": message.session_id,
                }
                (run_dir / "run.json").write_text(json.dumps(record, indent=2, default=str))
                log(f"\n--- {message.subtype}: {message.num_turns} turns, "
                    f"{message.duration_ms / 60000:.1f} min, "
                    f"estimated cost ${message.total_cost_usd or 0:.2f}")
                break
    progress.close()


if __name__ == "__main__":
    asyncio.run(main())
