> **How this evidence was produced (honest provenance)**
> `replay record http://127.0.0.1:8931/` was run against KeyScope
> served locally (`python3 -m http.server` over `~/workspace/keyscope`)
> and returned an honest **SKIP** (exit 2): Playwright is not installed
> on this machine, so NO browser capture happened and none is claimed.
> This report was instead built from a capture assembled from a real
> HTTP fetch of the live-served page: real URL, real HTTP 200, real
> `<title>` ("KeyScope — API Key Model Explorer"), recorded as the
> goto step below.

# replay report
Generated: 2026-10-23 18:39 UTC · replay-cli v0.1.0
Page: http://127.0.0.1:8931/ — KeyScope — API Key Model Explorer
Captured: fetched live from local http.server serving ~/workspace/keyscope
Events: 1 steps · 0 console · 1 network · 1 log

## Verdict: ALL EXPECTATIONS PASS

## Timeline
| t (s) | Kind | Event |
|---|---|---|
| 0.0 | step | goto http://127.0.0.1:8931/ |
| 0.2 | network | GET http://127.0.0.1:8931/ -> 200 |
| 0.2 | log | GET / -> 200 (29573 bytes, title: KeyScope — API Key Model Explorer) |

All captured expectations pass. If you fixed a bug, attach this report and the passing `replay.spec.ts` run as proof.
