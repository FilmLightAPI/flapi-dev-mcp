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
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fixture  # noqa: E402  (evals/fixture.py)
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
# Read-only helpers agents chain onto script runs (`... | head`, `; wc -l`).
SAFE_SHELL = ["head", "tail", "wc", "cat", "ls", "grep", "echo", "file", "mkdir"]
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif"}
OUTPUT_EXT = {".html", ".pdf"}


def _claude_args(prompt: str, mcp_config: Path, model: str | None,
                 run: bool = False, work: Path | None = None,
                 app_script: bool = False) -> list[str]:
    allowed = ["Read", "Glob", "Grep", "ToolSearch", "Write(./**)", "Edit(./**)",
               *[f"mcp__{SERVER}__{t}" for t in READ_ONLY_TOOLS]]
    if run:
        # Only the project's own venv interpreter may run, nothing else in Bash.
        allowed += ["Bash(.venv/bin/python:*)", "Bash(./.venv/bin/python:*)",
                    f"Bash({work}/.venv/bin/python:*)",
                    *[f"Bash({t}:*)" for t in SAFE_SHELL]]
    if app_script:
        # Real deploy: write into the dirs Baselight/Daylight scan, syntax-check
        # with the build's venv, and reload. The harness removes the files after.
        # File-write permissions are Edit(...) rules. Allow each deploy dir by
        # both its configured and resolved path (/vol/.support is a symlink).
        dirs = {p for d in fixture.deploy_dirs() for p in (d, str(Path(d).resolve()))}
        allowed += [f"{t}(/{d}/**)" for d in sorted(dirs) for t in ("Edit", "Write")]
        allowed += [f"mcp__{SERVER}__reload_app_scripts",
                    f"Bash({fixture.app_python()} -m py_compile:*)"]
    args = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--mcp-config", str(mcp_config), "--strict-mcp-config",
            "--no-session-persistence", "--allowedTools", *allowed]
    if not run:
        args += ["--disallowedTools", "Bash"]
    if model:
        args += ["--model", model]
    return args


def run_one(case: dict, n: int, outdir: Path, mcp_config: Path, model: str | None,
            timeout: int) -> dict:
    rundir = outdir / f"{case['id']}-{n}"
    rundir.mkdir(parents=True, exist_ok=True)
    # Resolve: macOS temp dirs live under /var -> /private/var, and a path the
    # agent sees one way must match permission rules written the other way.
    work = Path(tempfile.mkdtemp(prefix=f"flapi-eval-{case['id']}-")).resolve()
    scene = f"{case['id']}-{n}"
    prompt = case["prompt"].format(scene=fixture.scene_path(scene))
    for name, body in case.get("files", {}).items():
        (work / name).write_text(body)
    app_script = bool(case.get("app_script"))
    before = fixture.deployed() if app_script else set()
    try:
        p = subprocess.run(_claude_args(prompt, mcp_config, model, case.get("run", False), work,
                                        app_script),
                           cwd=work, capture_output=True, text=True, timeout=timeout)
        stream = p.stdout
    except subprocess.TimeoutExpired as e:
        stream = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
    (rundir / "transcript.jsonl").write_text(stream)
    code = {}
    for f in work.rglob("*"):
        if f.is_file() and f.suffix in CODE_EXT and ".venv" not in f.parts:
            code[str(f.relative_to(work))] = f.read_text(errors="replace")
    (rundir / "code.json").write_text(json.dumps(code, indent=2))
    # Real outcomes, checked outside the agent: files it produced, and the scene.
    extra = {"images": sorted(str(f.relative_to(work)) for f in work.rglob("*")
                              if f.suffix.lower() in IMAGE_EXT and ".venv" not in f.parts),
             "outputs": sorted(str(f.relative_to(work)) for f in work.rglob("*")
                               if f.suffix.lower() in OUTPUT_EXT and ".venv" not in f.parts)}
    if case.get("verify", {}).get("marks"):
        extra["marks"] = fixture.marks(scene)
    # Real images in any HTML it produced (data: URIs or files that exist).
    extra["html_imgs"] = 0
    for f in work.rglob("*.html"):
        if ".venv" in f.parts:
            continue
        for src_ in re.findall(r'<img[^>]+src="([^"]+)"', f.read_text(errors="replace")):
            if src_.startswith("data:image") or (f.parent / src_).is_file():
                extra["html_imgs"] += 1
    if "rerun_mentions" in case.get("verify", {}):
        # Re-run the agent's script ourselves (read-only cases only) and keep
        # its full output, independent of how the agent displayed it.
        scripts = [f for f in code if f.endswith(".py")]
        py = work / ".venv" / "bin" / "python"
        if len(scripts) == 1 and py.exists():
            r = subprocess.run([str(py), scripts[0]], cwd=work, capture_output=True,
                               text=True, timeout=300)
            extra["rerun"] = {"code": r.returncode, "output": (r.stdout + r.stderr)[-20000:]}
    if app_script:
        new = sorted(fixture.deployed() - before)
        extra["deployed"] = new
        extra["load"] = fixture.verify_app_scripts(new)
        for path in new:                        # deployed code counts as the run's code
            try:
                code[path] = Path(path).read_text(errors="replace")
            except OSError:
                pass
        (rundir / "code.json").write_text(json.dumps(code, indent=2))
        fixture.undeploy(new)
    (rundir / "extra.json").write_text(json.dumps(extra, indent=2))
    return score(case, stream, code, extra) | {"id": case["id"], "run": n}


def _events(stream: str) -> tuple[list[str], dict, list[dict]]:
    """Ordered tool names called (MCP prefix stripped), the final result event,
    and every Bash run as {cmd, error, output}."""
    calls, result, runs, pending = [], {}, [], {}
    for line in stream.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    calls.append(c["name"].removeprefix(f"mcp__{SERVER}__"))
                    if c["name"] == "Bash":
                        pending[c["id"]] = c["input"].get("command", "")
        elif ev.get("type") == "user":
            for c in ev.get("message", {}).get("content", []):
                if isinstance(c, dict) and c.get("tool_use_id") in pending:
                    out = c.get("content")
                    if isinstance(out, list):
                        out = " ".join(x.get("text", "") for x in out if isinstance(x, dict))
                    runs.append({"cmd": pending.pop(c["tool_use_id"]),
                                 "error": bool(c.get("is_error")), "output": str(out)[:2000]})
        elif ev.get("type") == "result":
            result = ev
    return calls, result, runs


def score(case: dict, stream: str, code: dict, extra: dict | None = None) -> dict:
    calls, result, runs = _events(stream)
    extra = extra or {}
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
        # Headless thumbnails go through Export.do_export_still. ThumbnailManager's
        # URI calls need the app, i.e. an App Script.
        checks["thumbnails_ok"] = app_script or "do_export_still(" in src
    # Execution: the agent ran its script with the project venv, and the last
    # run succeeded. Then the real outcome, checked outside the agent.
    ver = case.get("verify", {})
    if case.get("run"):
        script_runs = [r for r in runs if ".venv/bin/python" in r["cmd"]
                       and "py_compile" not in r["cmd"]]
        checks["ran_script"] = bool(script_runs)
        checks["last_run_ok"] = bool(script_runs) and not script_runs[-1]["error"]
        if "output_mentions" in ver:
            checks["output_mentions"] = any(ver["output_mentions"] in r["output"] for r in script_runs)
    if "rerun_mentions" in ver:
        rr = extra.get("rerun", {})
        checks["rerun_ok"] = rr.get("code") == 0
        checks["rerun_mentions"] = ver["rerun_mentions"] in rr.get("output", "")
    if "min_images" in ver:
        checks[f"images>={ver['min_images']}"] = len(extra.get("images", [])) >= ver["min_images"]
    if ver.get("any_output"):
        checks["produced_output"] = bool(extra.get("images") or extra.get("outputs"))
    if "min_shown_images" in ver:
        checks[f"shows>={ver['min_shown_images']}_images"] = (
            max(len(extra.get("images", [])), extra.get("html_imgs", 0)) >= ver["min_shown_images"])
    if ver.get("app_script_loads"):
        load = extra.get("load", {})
        checks["deployed"] = bool(extra.get("deployed"))
        checks["loaded_in_app"] = bool(load.get("loaded")) and not load.get("missing")
        checks["no_load_errors"] = not load.get("errors")
        checks["agent_reloaded"] = "reload_app_scripts" in calls
    if ver.get("marks"):
        m = extra.get("marks", {})
        want = ver["marks"]
        checks[f"marks=={len(want)}"] = m.get("count") == len(want)
        checks["mark_notes"] = sorted(m.get("notes", [])) == sorted(want)
    # Global checks on every run.
    unofficial = unofficial_calls(src)
    checks["official_api_only"] = not unofficial
    if not exp.get("code_optional"):
        checks["wrote_code"] = bool(code)
    checks["no_static_app_call"] = re.search(r"flapi\.Application\.(?!get\b)\w+\(", src) is None

    return {
        "unofficial_calls": unofficial,
        "passed": all(checks.values()),
        "checks": checks,
        "flapi_calls": [c for c in calls if c in READ_ONLY_TOOLS],
        "cost_usd": result.get("total_cost_usd"),
        "turns": result.get("num_turns"),
    }


_SCHEMA_METHODS: dict[str, set[str]] | None = None


def _schema_methods() -> dict[str, set[str]]:
    """Class -> method names from the target build's schema (official FLAPI)."""
    global _SCHEMA_METHODS
    if _SCHEMA_METHODS is None:
        from flapi_dev_mcp import schema
        path = schema.active_schema_path()
        d = json.loads(Path(path).read_text()) if path else {"Classes": []}
        _SCHEMA_METHODS = {c["Name"]: {m["Name"] for m in c.get("Methods", [])}
                           for c in d["Classes"]}
    return _SCHEMA_METHODS


def unofficial_calls(src: str) -> list[str]:
    """`Class.method(` calls on FLAPI classes (e.g. conn.Scene.open_scene,
    flapi.Export.do_export_still) whose method isn't in the build's schema."""
    methods = _schema_methods()
    bad = set()
    for cls, meth in re.findall(r"\b([A-Z]\w+)\.([a-z_]\w*)\s*\(", src):
        if cls in methods and meth not in methods[cls]:
            bad.add(f"{cls}.{meth}")
    # Any class reached through a connection (conn.X.y) must exist at all, so
    # classes that aren't in this build (e.g. an experiment) are caught too.
    for cls, meth in re.findall(r"\bconn\w*\.([A-Z]\w+)\.([a-z_]\w*)\s*\(", src):
        if cls not in methods:
            bad.add(f"{cls}.{meth}")
    return sorted(bad)


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
    ap.add_argument("--keep", action="store_true", help="keep the flapi_eval job afterwards")
    ap.add_argument("--coverage", action="store_true",
                    help="measure MCP server code coverage across the runs (coverage.txt)")
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
    py = str(REPO / ".venv" / "bin" / "python")
    server = {"command": py, "args": ["-m", "flapi_dev_mcp"]}
    if a.coverage:
        # Measure which server code the agents actually exercise.
        server = {"command": py, "args": ["-m", "coverage", "run", f"--rcfile={HERE / 'coveragerc'}",
                                          "-m", "flapi_dev_mcp"],
                  "env": {"COVERAGE_FILE": str(outdir / ".coverage")}}
    mcp_config.write_text(json.dumps({"mcpServers": {SERVER: server}}))

    if a.rescore:
        results = []
        for c in cases:
            for d in sorted(outdir.glob(f"{c['id']}-*")):
                code = json.loads((d / "code.json").read_text())
                ex = d / "extra.json"
                extra = json.loads(ex.read_text()) if ex.exists() else None
                results.append(score(c, (d / "transcript.jsonl").read_text(), code, extra)
                               | {"id": c["id"], "run": int(d.name.rsplit("-", 1)[1])})
        report = summarize(results, a.label)
        (outdir / "summary.md").write_text(report + "\n")
        print(report)
        return 0

    jobs = [(c, n) for c in cases for n in range(1, a.runs + 1)]
    fx = fixture.setup([f"{c['id']}-{n}" for c, n in jobs])
    if not fx.get("ok"):
        print(f"fixture setup failed: {fx}", file=sys.stderr)
        return 1
    try:
        def go(j):
            return run_one(j[0], j[1], outdir, mcp_config, a.model, a.timeout)
        # App Script runs reload the app's scripts, which is global, so they go
        # one at a time after the parallel batch.
        with ThreadPoolExecutor(a.parallel) as ex:
            results = list(ex.map(go, [j for j in jobs if not j[0].get("app_script")]))
        results += [go(j) for j in jobs if j[0].get("app_script")]
    finally:
        if not a.keep:
            fixture.teardown()
    (outdir / "results.json").write_text(json.dumps(results, indent=2))
    if a.coverage:
        env = {**os.environ, "COVERAGE_FILE": str(outdir / ".coverage")}
        rc = ["--rcfile", str(HERE / "coveragerc")]
        subprocess.run([py, "-m", "coverage", "combine", *rc], env=env, capture_output=True)
        cov = subprocess.run([py, "-m", "coverage", "report", *rc], env=env,
                             capture_output=True, text=True).stdout
        (outdir / "coverage.txt").write_text(cov)
    report = summarize(results, a.label)
    (outdir / "summary.md").write_text(report + "\n")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
