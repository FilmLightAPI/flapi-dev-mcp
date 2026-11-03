"""Guards for reload confirmation and the no-app-log message (Baselight 7.0.1
accepts a reload but writes no app-script log; the agent must be told)."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from flapi_dev_mcp import app_scripts

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import run  # noqa: E402


class _Resp(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _ps(pids: list[str]):
    """Fake `ps` output with one `flapi-plugins.py app` per PID, served in turn."""
    calls = iter(pids)
    def run_(args, **kw):
        out = ""
        if args[0] == "ps":
            pid = next(calls, pids[-1])
            out = f" {pid} /Library/Python -P /x/share/flapi-plugins.py app /scripts\n"
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
    return run_


@pytest.mark.parametrize("pids,restarted", [(["100", "200"], True), (["100", "100"], False)])
def test_reload_confirms_restart(monkeypatch, pids, restarted):
    monkeypatch.setattr(app_scripts.subprocess, "run", _ps(pids))
    monkeypatch.setattr(app_scripts.urllib.request, "urlopen", lambda *a, **k: _Resp(b"ok"))
    monkeypatch.setattr(app_scripts.time, "sleep", lambda s: None)
    r = app_scripts.reload_app_scripts("ui", wait=0.01)
    assert r["url"].endswith(":1985/reload-scripts") and r["restarted"] is restarted
    assert ("action" in r) is (not restarted)          # tells the agent to ask for a manual reload


def test_server_reload_uses_flapid_port(monkeypatch):
    monkeypatch.setattr(app_scripts.subprocess, "run", _ps(["1", "2"]))
    monkeypatch.setattr(app_scripts.urllib.request, "urlopen", lambda *a, **k: _Resp(b"ok"))
    assert app_scripts.reload_app_scripts("server", wait=0.01)["url"].endswith(":1984/reload-scripts")


def test_app_log_missing_folder_explains(monkeypatch, tmp_path):
    monkeypatch.setattr(app_scripts, "_gui_baselight_pid", lambda: "42")
    monkeypatch.setattr(app_scripts, "_fltmpdir", lambda pid: str(tmp_path / "never-created"))
    r = app_scripts.get_app_script_log()
    assert r["ok"] is False and r["log_available"] is False
    assert "own log file" in r["error"] and "menu item" in r["error"]


def test_no_app_log_build_needs_manual_check_not_failure():
    case = {"id": "menu-item", "app_script": True, "expect": {"code_optional": True},
            "verify": {"app_script_loads": True}}
    extra = {"deployed": ["/vol/.support/scripts/x.py"],
             "load": {"manual": True, "reloaded": True, "loaded": [], "missing": [], "errors": []}}
    stream = '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"1","name":"mcp__flapi-dev__reload_app_scripts","input":{}}]}}'
    res = run.score(case, stream, {"x.py": "import flapi"}, extra)
    assert res["passed"] and res["needs_manual_check"] and "loaded_in_app" not in res["checks"]
