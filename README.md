# salmon-demo-corpus

Agent-built corpus of interoperable Pacific salmon datasets for the PICES-2026
S12 demo of the salmon data integration toolkit (talk: Wed 28 Oct 2026).

Agents run through the Claude Agent SDK and are paid by the monthly
promotional API credit of the Console organization "Brett's Individual Org"
(not by a Claude subscription).

## Setup

1. Store the Console API key in the macOS Keychain (one time):

   ```bash
   security add-generic-password -a "$USER" -s anthropic-salmon-corpus -w
   ```

2. Install dependencies: `uv sync`

3. Check the connection: `uv run smoke_test.py` (spends at most about $0.50).
   Then confirm the run on the Console Usage page.

`corpus_auth.py` reads the key from the Keychain and clears any Claude session
variables inherited from the shell, so a run never uses a session's account.
