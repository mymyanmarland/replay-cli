#!/usr/bin/env python3
"""replay-cli — capture a real web bug once, replay it forever.

A capture (JSON: steps + console + network + logs) is merged onto ONE
timeline, deduplicated, secret-redacted, and turned into:

  * ``replay-report.md`` — verdict (BUG REPRODUCED / ALL EXPECTATIONS
    PASS) plus the unified timeline an agent can read in one pass, and
  * ``replay.spec.ts`` — a Playwright test generated from the captured
    steps, with assertions for the expected network outcomes, so any
    agent can re-run it to prove a fix (FAIL before, PASS after).

Core is stdlib only. Playwright is used opportunistically by
``record`` when it happens to be installed; it is never required, and
its absence is an honest SKIP, never a fabricated capture.
"""
import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone

VERSION = "0.1.0"

# ---------------------------------------------------------------- redaction
_SECRET_PATTERNS = [
    # Authorization: Bearer xxx / Basic xxx
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer|basic)\s+\S+"),
     r"\1\2 ***REDACTED***"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*)\S+"), r"\1***REDACTED***"),
    # Cookie / Set-Cookie headers
    (re.compile(r"(?i)((?:set-)?cookie\s*[:=]\s*)[^\n;]+"), r"\1***REDACTED***"),
    # key=value style secrets anywhere in a string
    (re.compile(r"(?i)\b(token|api[_-]?key|apikey|password|passwd|secret|"
                r"session|sessionid|auth)\s*=\s*[^\s&;,'\"]+"),
     r"\1=***REDACTED***"),
    # JSON style "token": "xxx"
    (re.compile(r"(?i)\"(token|api[_-]?key|password|secret|cookie|"
                r"authorization)\"\s*:\s*\"[^\"]*\""),
     r'"\1": "***REDACTED***"'),
    # bare bearer tokens
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer ***REDACTED***"),
]

_SECRET_KEYS = {"authorization", "cookie", "set-cookie", "token",
                "api_key", "apikey", "api-key", "password", "passwd",
                "secret", "session", "sessionid", "auth"}


def redact(text):
    """Remove secret values from a string. Idempotent."""
    if text is None:
        return ""
    s = str(text)
    for pat, repl in _SECRET_PATTERNS:
        s = pat.sub(repl, s)
    return s


def redact_obj(obj):
    """Deep-redact a parsed JSON value (dict keys + string values)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in _SECRET_KEYS:
                out[k] = "***REDACTED***"
            else:
                out[k] = redact_obj(v)
        return out
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, str):
        return redact(obj)
    return obj


# ---------------------------------------------------------------- capture
class CaptureError(ValueError):
    pass


def load_capture(path):
    try:
        with open(path, errors="replace") as f:
            data = json.load(f)
    except OSError as e:
        raise CaptureError(f"cannot read capture: {e}")
    except json.JSONDecodeError as e:
        raise CaptureError(f"capture is not valid JSON: {e}")
    return validate_capture(data)


def validate_capture(data):
    if not isinstance(data, dict):
        raise CaptureError("capture must be a JSON object")
    if not data.get("url"):
        raise CaptureError("capture.url is required")
    for key in ("steps", "console", "network", "logs"):
        if key in data and not isinstance(data[key], list):
            raise CaptureError(f"capture.{key} must be a list")
    cap = {"url": str(data["url"]),
           "started_at": data.get("started_at", ""),
           "title": data.get("title", ""),
           "expect_no_console_errors": data.get(
               "expect_no_console_errors", True),
           "steps": data.get("steps") or [],
           "console": data.get("console") or [],
           "network": data.get("network") or [],
           "logs": data.get("logs") or []}
    return redact_obj(cap)


# ---------------------------------------------------------------- timeline
def _signature(kind, text):
    s = re.sub(r"\b\d+\b", "N", text)
    s = re.sub(r"\s+", " ", s).strip()
    return f"{kind}:{s[:200]}"


def build_timeline(cap):
    """Merge steps/console/network/logs on one timeline sorted by t.

    Repeated console errors and repeated identical network results are
    deduplicated into one entry with a count (``×N``).
    Returns (events, failures) where events are display dicts with
    keys t, kind, text, count, fail.
    """
    events = OrderedDict()  # signature -> event
    failures = []

    def add(t, kind, text, fail=False, dedupe=True):
        text = redact(text)
        sig = _signature(kind, text) if dedupe else \
            f"{kind}:{len(events)}:{text[:200]}"
        if sig in events:
            events[sig]["count"] += 1
            return events[sig]
        ev = {"t": float(t or 0), "kind": kind, "text": text,
              "count": 1, "fail": fail}
        events[sig] = ev
        return ev

    for st in cap["steps"]:
        typ = st.get("type", "step")
        what = st.get("selector") or st.get("text") or st.get("url") or ""
        label = f"{typ} {what}".strip()
        if st.get("value"):
            label += f" = {st['value']}"
        add(st.get("t", 0), "step", label, dedupe=False)

    for c in cap["console"]:
        level = str(c.get("level", "log")).lower()
        fail = level == "error" and cap["expect_no_console_errors"]
        ev = add(c.get("t", 0), f"console/{level}", c.get("text", ""),
                 fail=fail)
        if fail and ev["count"] == 1:
            failures.append(f"console error at t={ev['t']:.1f}s: "
                            f"{ev['text']}")

    for n in cap["network"]:
        method = str(n.get("method", "GET")).upper()
        url = n.get("url", "")
        status = n.get("status")
        expected = n.get("expected_status")
        label = f"{method} {url} -> {status}"
        if expected is not None:
            fail = status != expected
        else:
            fail = isinstance(status, int) and status >= 400
        ev = add(n.get("t", 0), "network", label, fail=fail)
        if fail and ev["count"] == 1:
            if expected is not None:
                failures.append(
                    f"{method} {redact(url)} returned {status}, "
                    f"expected {expected} (t={ev['t']:.1f}s)")
            else:
                failures.append(
                    f"{method} {redact(url)} failed with {status} "
                    f"(t={ev['t']:.1f}s)")

    for lg in cap["logs"]:
        add(lg.get("t", 0), "log", lg.get("text", ""))

    ordered = sorted(events.values(), key=lambda e: e["t"])
    return ordered, failures


def verdict_of(failures):
    return "BUG REPRODUCED" if failures else "ALL EXPECTATIONS PASS"


# ---------------------------------------------------------------- spec.ts
def _ts_str(s):
    return "'" + redact(str(s)).replace("\\", "\\\\").replace("'", "\\'") + "'"


def generate_spec(cap):
    """Generate a Playwright test from the captured steps."""
    lines = [
        "// Generated by replay-cli v" + VERSION + " — do not edit by hand.",
        "// Re-run after a fix: this test must go from FAIL to PASS.",
        "import { test, expect } from '@playwright/test';",
        "",
        f"test('replay: {redact(cap.get('title') or cap['url'])}', "
        "async ({ page }) => {",
        "  const responses: { url: string; status: number }[] = [];",
        "  const failed: string[] = [];",
        "  page.on('response', (r) => {",
        "    responses.push({ url: r.url(), status: r.status() });",
        "    if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);",
        "  });",
        "  const consoleErrors: string[] = [];",
        "  page.on('console', (m) => {",
        "    if (m.type() === 'error') consoleErrors.push(m.text());",
        "  });",
        "",
    ]
    for st in cap["steps"]:
        typ = st.get("type", "goto")
        if typ == "goto":
            lines.append(f"  await page.goto({_ts_str(st.get('url') or cap['url'])});")
        elif typ == "click":
            if st.get("selector"):
                lines.append(f"  await page.locator({_ts_str(st['selector'])}).click();")
            elif st.get("text"):
                lines.append(f"  await page.getByText({_ts_str(st['text'])}).click();")
        elif typ == "fill":
            target = st.get("selector") or ""
            lines.append(f"  await page.locator({_ts_str(target)}).fill({_ts_str(st.get('value', ''))});")
        elif typ == "wait":
            lines.append(f"  await page.waitForTimeout({int(st.get('ms', 500))});")
        else:
            lines.append(f"  // step: {redact(typ)} {redact(st.get('selector') or st.get('text') or '')}")
    lines.append("")
    for n in cap["network"]:
        if n.get("expected_status") is not None:
            key = _url_key(n["url"])
            msg = (f"expected {n.get('method', 'GET')} {key} "
                   f"-> {int(n['expected_status'])}")
            lines.append(
                f"  expect(responses.filter((r) => r.url.includes("
                f"{_ts_str(key)}) && r.status === "
                f"{int(n['expected_status'])}).length, {_ts_str(msg)})"
                f".toBeGreaterThan(0);")
    lines.append("  expect(failed, 'no request should fail').toEqual([]);")
    if cap["expect_no_console_errors"]:
        lines.append("  expect(consoleErrors, 'no console errors').toEqual([]);")
    lines += ["});", ""]
    return "\n".join(lines)


def _url_key(url):
    """A short, stable substring of a URL for spec matching."""
    u = redact(str(url))
    return u if len(u) <= 80 else u[-80:]


# ---------------------------------------------------------------- report
def build_report(cap):
    events, failures = build_timeline(cap)
    verdict = verdict_of(failures)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        "# replay report",
        f"Generated: {now} · replay-cli v{VERSION}",
        f"Page: {redact(cap['url'])}"
        + (f" — {redact(cap['title'])}" if cap.get("title") else ""),
        f"Captured: {cap.get('started_at') or 'unknown'}",
        f"Events: {len(cap['steps'])} steps · {len(cap['console'])} "
        f"console · {len(cap['network'])} network · {len(cap['logs'])} log",
        "",
        f"## Verdict: {verdict}",
        "",
    ]
    if failures:
        out.append("## Failed expectations")
        for f_ in failures:
            out.append(f"- {f_}")
        out.append("")
    out += [
        "## Timeline",
        "| t (s) | Kind | Event |",
        "|---|---|---|",
    ]
    for ev in events:
        text = ev["text"].replace("|", "/")
        if ev["count"] > 1:
            text += f" (×{ev['count']})"
        mark = " ❌" if ev["fail"] else ""
        out.append(f"| {ev['t']:.1f} | {ev['kind']} | {text}{mark} |")
    if not events:
        out.append("| 0.0 | - | (empty capture) |")
    out.append("")
    if failures:
        out += ["## Fix these first",
                "1. Reproduce with `replay.spec.ts` (it should FAIL now).",
                "2. Fix the first failed expectation above.",
                "3. Re-run the spec and `replay check` — both must PASS "
                "before reporting the bug fixed."]
    else:
        out.append("All captured expectations pass. If you fixed a bug, "
                   "attach this report and the passing `replay.spec.ts` "
                   "run as proof.")
    out.append("")
    return "\n".join(out), verdict, failures


def check_capture(cap):
    _, verdict, failures = build_report(cap)
    return verdict, failures


# ---------------------------------------------------------------- record
def record_capture(url):
    """Real capture via Playwright — or an honest SKIP.

    Returns (capture_dict, None) on success, (None, reason) otherwise.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, ("playwright not installed — capture skipped "
                      "(core report/check are stdlib-only). Install "
                      "with: pip install playwright && "
                      "playwright install chromium — or paste "
                      "recorder.js into the page and save the capture "
                      "JSON manually.")
    cap = {"url": url, "started_at": datetime.now(timezone.utc).isoformat(),
           "title": "", "steps": [], "console": [], "network": [],
           "logs": []}
    import time as _time
    start = _time.monotonic()

    def t():
        return round(_time.monotonic() - start, 3)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.on("console", lambda m: cap["console"].append(
                {"t": t(), "level": m.type, "text": m.text}))
            page.on("response", lambda r: cap["network"].append(
                {"t": t(), "method": r.request.method, "url": r.url,
                 "status": r.status}))
            page.goto(url, timeout=15000)
            cap["title"] = page.title()
            cap["steps"].append({"t": t(), "type": "goto", "url": url})
            browser.close()
    except Exception as e:  # browser missing, page unreachable, ...
        return None, f"playwright present but capture failed: {e}"
    return validate_capture(cap), None


# ---------------------------------------------------------------- MCP
def mcp_server():
    """Minimal stdio MCP server exposing replay_report + replay_check."""
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    tools = [
        {"name": "replay_report",
         "description": "Build a replay report (timeline + verdict + "
                        "generated Playwright spec) from a capture JSON "
                        "file or capture object.",
         "inputSchema": {"type": "object", "properties": {
             "capture_path": {"type": "string"},
             "capture": {"type": "object"}}}},
        {"name": "replay_check",
         "description": "Check a capture's expectations: returns "
                        "ALL EXPECTATIONS PASS or BUG REPRODUCED with "
                        "the failed expectations.",
         "inputSchema": {"type": "object", "properties": {
             "capture_path": {"type": "string"},
             "capture": {"type": "object"}}}},
    ]
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method, rid = req.get("method"), req.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "replay-cli", "version": VERSION}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}})
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                if args.get("capture") is not None:
                    cap = validate_capture(args["capture"])
                else:
                    cap = load_capture(args.get("capture_path", ""))
                if name == "replay_check":
                    verdict, failures = check_capture(cap)
                    text = verdict + ("\n" + "\n".join(
                        f"- {f_}" for f_ in failures) if failures else "")
                else:
                    report, _, _ = build_report(cap)
                    text = report + "\n---\n" + generate_spec(cap)
            except (CaptureError, OSError) as e:
                text = f"error: {e}"
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [
                {"type": "text", "text": text}]}})
        elif rid is not None:
            send({"jsonrpc": "2.0", "id": rid,
                  "error": {"code": -32601, "message": "method not found"}})


# ---------------------------------------------------------------- CLI
def _write_outputs(cap, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    report, verdict, _ = build_report(cap)
    spec = generate_spec(cap)
    report_path = os.path.join(out_dir, "replay-report.md")
    spec_path = os.path.join(out_dir, "replay.spec.ts")
    with open(report_path, "w") as f:
        f.write(report)
    with open(spec_path, "w") as f:
        f.write(spec)
    return report_path, spec_path, verdict


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="replay",
        description="Capture a real web bug once; replay it to prove "
                    "the fix.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="Capture JSON -> report + spec")
    r.add_argument("capture", help="Capture JSON file")
    r.add_argument("--out", default=".", help="Output directory")
    c = sub.add_parser("check", help="Exit 0 if all expectations pass, "
                                     "1 if the bug is reproduced")
    c.add_argument("capture", help="Capture JSON file")
    rec = sub.add_parser("record", help="Capture a page with Playwright "
                                        "(SKIP, honestly, if unavailable)")
    rec.add_argument("url", help="Page URL to capture")
    rec.add_argument("--out", default=".", help="Output directory")
    sub.add_parser("mcp", help="Run the stdio MCP server")
    args = ap.parse_args(argv)

    if args.cmd == "mcp":
        mcp_server()
        return 0
    if args.cmd == "record":
        cap, reason = record_capture(args.url)
        if cap is None:
            print(f"SKIP: {reason}")
            return 2
        cap_path = os.path.join(args.out, "capture.json")
        os.makedirs(args.out, exist_ok=True)
        with open(cap_path, "w") as f:
            json.dump(cap, f, indent=2)
        rp, sp, verdict = _write_outputs(cap, args.out)
        print(f"{verdict}: wrote {cap_path}, {rp}, {sp}")
        return 0 if verdict == "ALL EXPECTATIONS PASS" else 1
    try:
        cap = load_capture(args.capture)
    except CaptureError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.cmd == "report":
        rp, sp, verdict = _write_outputs(cap, args.out)
        print(f"{verdict}: wrote {rp} and {sp}")
        return 0 if verdict == "ALL EXPECTATIONS PASS" else 1
    # check
    verdict, failures = check_capture(cap)
    print(verdict)
    for f_ in failures:
        print(f"- {f_}")
    return 0 if verdict == "ALL EXPECTATIONS PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
