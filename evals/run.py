"""Behavioral evals: does a coding agent use flapi-dev correctly from a plain-English prompt?

Runs each prompt in evals/prompts.json through headless Claude Code (`claude -p`)
in a fresh temp project, with only the flapi-dev MCP from this checkout, then
scores the tool calls and the code it wrote. Agents are nondeterministic, so
run each prompt several times and read the rates, not single results.

    .venv/bin/python evals/run.py --label A --runs 3
    .venv/bin/python evals/run.py --label B --runs 3 --only web-cursor,layers

Safe on a real Baselight machine: no Bash, file writes only inside the temp
project, and the MCP tools that change Baselight's venv or reload scripts are
not allowed. So scripts are written, not run.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SERVER = "flapi-dev"
READ_ONLY_TOOLS = [
    "flapi_dev_ping", "flapi_check_environment", "flapi_list_baselight_versions",
    "flapi_status", "get_api_surface", "search_examples", "get_class_docs",
    "check_app_script_readiness", "check_flapid", "flapi_connection",
    "check_standalone_readiness", "setup_standalone_env", "install_dependencies",
    "get_app_script_log", "get_flapi_log",
]
CODE_EXT = {".py", ".html", ".js", ".sh"}


def _claude_args(prompt: str, mcp_config: Path, model: str | None) -> list[str]:
    allowed = ["Read", "Glob", "Grep", "ToolSearch", "Write(./**)", "Edit(./**)",
               *[f"mcp__{SERVER}__{t}" for t in READ_ONLY_TOOLS]]
    args = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--mcp-config", str(mcp_config), "--strict-mcp-config",
            "--no-session-persistence", "--allowedTools", *allowed,
            "--disallowedTools", "Bash"]
    if model:
        args += ["--model", model]
    return args


def run_one(case: dict, n: int, outdir: Path, mcp_config: Path, model: str | None,
            timeout: int) -> dict:
    rundir = outdir / f"{case['id']}-{n}"
    rundir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"flapi-eval-{case['id']}-"))
    try:
        p = subprocess.run(_claude_args(case["prompt"], mcp_config, model), cwd=work,
                           capture_output=True, text=True, timeout=timeout)
        stream = p.stdout
    except subprocess.TimeoutExpired as e:
        stream = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
    (rundir / "transcript.jsonl").write_text(stream)
    code = {}
    for f in work.rglob("*"):
        if f.is_file() and f.suffix in CODE_EXT and ".venv" not in f.parts:
            code[str(f.relative_to(work))] = f.read_text(errors="replace")
    (rundir / "code.json").write_text(json.dumps(code, indent=2))
    return score(case, stream, code) | {"id": case["id"], "run": n}


def _events(stream: str) -> tuple[list[str], dict]:
    """Ordered tool names called (MCP prefix stripped) and the final result event."""
    calls, result = [], {}
    for line in stream.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    calls.append(c["name"].removeprefix(f"mcp__{SERVER}__"))
        elif ev.get("type") == "result":
            result = ev
    return calls, result


def score(case: dict, stream: str, code: dict) -> dict:
    calls, result = _events(stream)
    src = "\n".join(code.values())
    exp = case.get("expect", {})
    checks: dict[str, bool] = {}

    first_write = next((i for i, c in enumerate(calls) if c in ("Write", "Edit")), len(calls))
    examples_first = "search_examples" in calls[:first_write]
    if exp.get("examples_before_code"):
        checks["examples_before_code"] = examples_first
    if "called_any" in exp:
        checks["called_" + "|".join(exp["called_any"])] = any(t in calls for t in exp["called_any"])
    for s in exp.get("code_requires", []):
        checks[f"has:{s}"] = s in src
    if "code_requires_any" in exp:
        checks["has-any:" + "|".join(exp["code_requires_any"])] = any(
            s in src for s in exp["code_requires_any"])
    for s in exp.get("code_forbids", []):
        checks[f"no:{s}"] = s.lower() not in src.lower()
    for rx in exp.get("code_forbids_regex", []):
        checks[f"no-re:{rx}"] = re.search(rx, src) is None
    app_script = "Connection.get(" in src or "MenuItem" in src
    if exp.get("live_app_access"):
        checks["live_app"] = "1985" in src or app_script
    if exp.get("thumbnails_valid"):
        # Headless thumbnails only through render_frame (newer builds). The
        # URI-based calls need the app, i.e. an App Script.
        uri_calls = re.search(r"get_(poster_uri|scrub_uri_template)\(", src)
        checks["thumbnails_ok"] = app_script or not uri_calls
    # Global checks on every run.
    if not exp.get("code_optional"):
        checks["wrote_code"] = bool(code)
    checks["no_static_app_call"] = re.search(r"flapi\.Application\.(?!get\b)\w+\(", src) is None

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "flapi_calls": [c for c in calls if c in READ_ONLY_TOOLS],
        "cost_usd": result.get("total_cost_usd"),
        "turns": result.get("num_turns"),
    }


def summarize(results: list[dict], label: str) -> str:
    by_id: dict[str, list[dict]] = {}
    for r in results:
        by_id.setdefault(r["id"], []).append(r)
    lines = [f"## Eval {label}", "", "| prompt | pass | failed checks | flapi tools used |",
             "|---|---|---|---|"]
    for cid, rs in by_id.items():
        fails = sorted({k for r in rs for k, v in r["checks"].items() if not v})
        tools = sorted({t for r in rs for t in r["flapi_calls"]})
        lines.append(f"| {cid} | {sum(r['passed'] for r in rs)}/{len(rs)} | "
                     f"{', '.join(fails) or '-'} | {', '.join(tools) or 'none'} |")
    cost = sum(r["cost_usd"] or 0 for r in results)
    lines += ["", f"Total: {sum(r['passed'] for r in results)}/{len(results)} passed, "
                  f"${cost:.2f}"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="results folder name, e.g. A or B")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", help="comma-separated prompt ids")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--model")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per run")
    ap.add_argument("--rescore", action="store_true",
                    help="re-score saved transcripts for --label without re-running")
    a = ap.parse_args()

    cases = json.loads((HERE / "prompts.json").read_text())
    if a.only:
        keep = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    outdir = HERE / "results" / a.label
    outdir.mkdir(parents=True, exist_ok=True)
    mcp_config = outdir / "mcp.json"
    mcp_config.write_text(json.dumps({"mcpServers": {SERVER: {
        "command": str(REPO / ".venv" / "bin" / "python"), "args": ["-m", "flapi_dev_mcp"]}}}))

    if a.rescore:
        results = []
        for c in cases:
            for d in sorted(outdir.glob(f"{c['id']}-*")):
                code = json.loads((d / "code.json").read_text())
                results.append(score(c, (d / "transcript.jsonl").read_text(), code)
                               | {"id": c["id"], "run": int(d.name.rsplit("-", 1)[1])})
        report = summarize(results, a.label)
        (outdir / "summary.md").write_text(report + "\n")
        print(report)
        return 0

    jobs = [(c, n) for c in cases for n in range(1, a.runs + 1)]
    with ThreadPoolExecutor(a.parallel) as ex:
        results = list(ex.map(lambda j: run_one(j[0], j[1], outdir, mcp_config, a.model,
                                                a.timeout), jobs))
    (outdir / "results.json").write_text(json.dumps(results, indent=2))
    report = summarize(results, a.label)
    (outdir / "summary.md").write_text(report + "\n")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
