# replay-cli — Spec v0.1

## Problem
A user reports a bug in one sentence — "I clicked pay and nothing
happened" — and the agent was not there. It never saw the steps, the
console, or the network. So it guesses, patches the wrong thing, and
cannot prove the fix: there is no reproduction to re-run. The oldest
time-sink in software: *cannot reproduce*.

## What it is
A tool that captures a real bug **once** and turns it into two
artifacts any agent can use:

- `replay-report.md` — steps, console, network and logs merged on ONE
  timeline, deduplicated, secrets redacted, with a machine-checkable
  verdict.
- `replay.spec.ts` — a Playwright test generated from the captured
  steps, asserting the expected network outcomes — FAIL before the
  fix, PASS after. The repro becomes the proof.

## Capture format (JSON)
```json
{
  "url": "https://shop.example.com/checkout",
  "title": "Checkout",
  "started_at": "2026-10-24T00:00:00Z",
  "expect_no_console_errors": true,
  "steps":   [{"t": 1.2, "type": "click", "selector": "#pay-button", "text": "Pay now"}],
  "console": [{"t": 2.1, "level": "error", "text": "Payment failed: 403"}],
  "network": [{"t": 2.0, "method": "POST", "url": "https://shop.example.com/api/pay",
               "status": 403, "expected_status": 200}],
  "logs":    [{"t": 2.0, "text": "POST /api/pay -> 403"}]
}
```
`t` is seconds since capture start. Expectations: a network entry
with `expected_status` must match it; any network status ≥ 400 without
a matching expectation is a failure; console errors are failures
unless `expect_no_console_errors` is false.

## Hard rules
1. **Verdict is machine-checkable.** `replay check` exits 0 on
   ALL EXPECTATIONS PASS, 1 on BUG REPRODUCED, 2 on a bad capture or
   an honest SKIP. Never soften a 1 into "probably fixed".
2. **Secrets never survive load.** Authorization, Cookie and
   token/password/secret values are redacted in every string and
   structured field before anything is written — report and spec
   included.
3. **Stdlib-only core.** Python 3, no pip installs, no API keys.
   Playwright is used by `record` only when already importable;
   without it, `record` is an honest SKIP with install instructions —
   never a fabricated capture.
4. **One timeline.** Four scattered sources are useless to an agent;
   one time-ordered, deduplicated timeline is the story of the bug.

## v0.1 scope
- `replay report <capture.json> [--out DIR]` — writes
  `replay-report.md` + `replay.spec.ts`.
- `replay check <capture.json>` — verdict + failed expectations,
  exit-code contract above.
- `replay record <url> [--out DIR]` — with Playwright: goto the page,
  capture title/console/network into `capture.json`, then report.
  Without: SKIP, exit 2.
- `replay mcp` — stdio MCP server: `replay_report`, `replay_check`.
- `recorder.js` — paste-into-the-page recorder producing the capture
  format from real clicks/fills/console/fetch/XHR.

## Out of scope for v0.1
- Full step recording via Playwright (clicks/fills during `record`)
- Desktop / mobile-app capture
- Hosted dashboards, accounts, CI services

## Success criteria
- Planted-bug fixture (pay click → POST /api/pay 403 vs expected
  200, plus a console error) → check exits 1, report names the 403 on
  the timeline; the fixed fixture (200) → exits 0.
- Fixture secrets (fake Authorization/Cookie/token values) appear in
  NO generated artifact.
- Unit tests pass; a real project produces an honest evidence report
  (a SKIP labelled as a SKIP counts — a fabricated capture does not).
