# replay-cli — agent skill

## The rule
**Never guess at a bug you have not replayed, and never report a bug
"fixed" without a passing replay.**

When a user says "it broke", the agent was not there: it did not see
the clicks, the screen, or the failed request. Guessing from that
sentence is how fixes miss. replay-cli turns one real occurrence into
a report any agent can read and a test any agent can re-run.

## When a bug is reported
1. Get a capture first — do not start by reading code and guessing.
   - If the user can reproduce it live, have them paste
     `recorder.js` into the page (DevTools console), reproduce the
     bug, and save `capture.json` — or run
     `python3 replay.py record <url>` when Playwright is installed.
   - If a capture already exists, use it.
2. Build and READ the report before touching code:
   ```bash
   python3 replay.py report capture.json --out .
   ```
   Read `replay-report.md`: the **verdict**, the **failed
   expectations**, then the **timeline** top to bottom. The timeline
   is the story of the bug — step, request, error, in time order.
3. Fix the FIRST failed expectation, not the loudest symptom.

## Proving the fix
1. Re-run the generated test: `replay.spec.ts` (Playwright) — it must
   pass against the fixed app.
2. Re-check a fresh capture of the fixed flow if you have one:
   ```bash
   python3 replay.py check capture-fixed.json   # exit 0 = PASS
   ```
3. Only then report the bug fixed — and cite the verdict. A capture
   that still exits 1 means **not fixed**, however good the code
   looks.

## Honesty rules
- **SKIP is honest, not success.** If `record` says Playwright is not
  installed, say exactly that — never invent a capture.
- **Secrets are redacted on load**, but never paste a raw capture
  containing real credentials into chat; use staging accounts.
- `×N` in the timeline means one event repeated N times, deduplicated
  — fix it once.

## MCP
`replay mcp` runs a stdio MCP server with two tools:
`replay_report` and `replay_check` (each takes `capture_path` or a
`capture` object):

```json
{ "command": "python3", "args": ["/path/to/replay.py", "mcp"] }
```
