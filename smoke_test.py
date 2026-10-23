"""Smallest real run: prove the Agent SDK works and bills the API credit.

Run with `uv run smoke_test.py`. It reads one local repository, spends at most
about MAX_BUDGET_USD, and prints the cost estimate. Afterwards, check the
Console Usage page to confirm the run appears under "Brett's Individual Org".
"""

import asyncio
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from corpus_auth import use_api_key_from_keychain

MODEL = "claude-opus-5-5"
MAX_BUDGET_USD = 0.50
PRIZE_REPO = Path.home() / "code" / "SalmonPrize_Diagnostics"

PROMPT = (
    "List the CSV files in this repository (at most 10) and, for each one, "
    "its column names. Reply with a short markdown table. Do not change any files."
)


async def main() -> None:
    use_api_key_from_keychain()

    options = ClaudeAgentOptions(
        model=MODEL,
        cwd=PRIZE_REPO,
        # Read-only tools, approved without prompts; nothing else is allowed.
        allowed_tools=["Read", "Glob", "Grep"],
        permission_mode="dontAsk",
        # Load no CLAUDE.md or settings files, so global instructions add no cost.
        setting_sources=[],
        max_turns=10,
        max_budget_usd=MAX_BUDGET_USD,
    )

    async for message in query(prompt=PROMPT, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
        elif isinstance(message, ResultMessage):
            cost = message.total_cost_usd or 0.0
            print(f"\n--- {message.subtype}: {message.num_turns} turns, "
                  f"{message.duration_ms / 1000:.0f} s, estimated cost ${cost:.4f}")
            if message.is_error:
                print("Errors:", message.errors or message.api_error_status)


if __name__ == "__main__":
    asyncio.run(main())
