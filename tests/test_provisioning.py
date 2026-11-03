"""Regression guards: init must target the right build, venv and examples for
release and dev builds alike (see conftest.fl_env for the fake installs)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

from flapi_dev_mcp import app_scripts, cli
from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc
from flapi_dev_mcp.discovery import detect_running_build as real_detect_running_build

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app layout")


def _init(env, dev: bool = True) -> dict:
    """What `init --dev-root <alias>:dev-build:slate` builds, saved like init saves it."""
    dev_roots = [(str(env.dev_alias), "dev-build", "slate")] if dev else []
    cfg = cfgmod.build_config(disc.discover(), dev_roots=dev_roots)
    cfgmod.save_config(cfg)
    return cfg


def _examples(cfg: dict) -> list[Path]:
    return [Path(s["path"]).resolve() for s in cfg["sources"] if s["type"] == "local"]


def test_dev_root_records_product_and_version(fl_env):
    cfg = _init(fl_env)
    dev = next(r for r in cfg["baselight_roots"] if r["kind"] == "dev-build")
    assert dev["product"] == "daylight"
    assert dev["version"] == "7.0.4.unknown"


def test_running_dev_build_becomes_default(fl_env):
    # Registered via the symlinked ~/Development path, running from the real path.
    fl_env.run_as(fl_env.dev_app)
    cfg = _init(fl_env)
    assert cfg["default_root"] == str(fl_env.dev_alias)
    assert cfg["baselight"]["active_venv"] == str(fl_env.dev_venv)
    assert _examples(cfg) == [(fl_env.dev_app / "Contents/share/flapi/examples/python").resolve()]


def test_running_release_stays_default_with_dev_registered(fl_env):
    fl_env.run_as(fl_env.rel_app, kind="release")
    cfg = _init(fl_env)
    assert cfg["default_root"] == str(fl_env.current)
    assert cfg["baselight"]["active_venv"] == str(fl_env.rel_venv)


def test_nothing_running_defaults_to_release(fl_env):
    cfg = _init(fl_env)
    assert cfg["default_root"] == str(fl_env.current)
    assert cfg["baselight"]["active_venv"] == str(fl_env.rel_venv)


def test_release_only_install(fl_env):
    fl_env.run_as(fl_env.rel_app, kind="release")
    cfg = _init(fl_env, dev=False)
    assert cfg["default_root"] == str(fl_env.current)
    assert cfg["baselight"]["active_venv"] == str(fl_env.rel_venv)
    assert _examples(cfg) == [(fl_env.rel_app / "Contents/share/flapi/examples/python").resolve()]


def test_missing_dev_venv_never_falls_back_to_release_venv(fl_env):
    # Dev build running but its venv not created yet: config must not claim one,
    # App Scripts must point at the dev build's (missing) venv, not the release
    # venv, and --create must come from the dev build.
    (fl_env.dev_venv / "bin" / "python").unlink()
    fl_env.run_as(fl_env.dev_app)
    cfg = _init(fl_env)
    assert cfg["baselight"]["active_venv"] is None
    assert app_scripts.managed_venv() == fl_env.dev_venv
    assert app_scripts._fl_setup_scripts().resolve() == (
        fl_env.dev_app / "Contents/bin/fl-setup-flapi-scripts").resolve()
    assert app_scripts.check_app_script_readiness("ui")["ready"] is False


def test_app_scripts_use_dev_build_venv(fl_env):
    fl_env.run_as(fl_env.dev_app)
    _init(fl_env)
    assert app_scripts.managed_venv() == fl_env.dev_venv


def test_target_running_uses_build_venv(fl_env):
    # Config initially targets the release build, then the dev build starts.
    _init(fl_env, dev=False)
    fl_env.run_as(fl_env.dev_app)
    assert cli._cmd_target_running(argparse.Namespace()) == 0
    cfg = cfgmod.load_config()
    assert Path(cfg["default_root"]).resolve() == fl_env.dev_app.resolve()
    assert cfg["baselight"]["active_venv"] == str(fl_env.dev_venv)



def test_detects_root_owned_flapid_on_mac(fl_env, monkeypatch):
    # `sudo fl-service` runs flapid as root: lsof (no sudo) sees no listener,
    # but pgrep still finds it. Detection must fall back to pgrep.
    import subprocess
    flici = fl_env.dev_alias / "Contents/bin/flici"

    def fake_run(args, **kw):
        out = {"lsof": "", "pgrep": "4242\n",
               "ps": f"{flici} {fl_env.dev_alias}/Contents/bin/flapid\n"}[Path(args[0]).name]
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    monkeypatch.setattr(disc.subprocess, "run", fake_run)
    br = real_detect_running_build()
    assert br is not None
    assert (br.product, br.kind) == ("daylight", "dev-build")
    assert br.app.resolve() == fl_env.dev_app.resolve()


def _run_init(fl_env, monkeypatch, capsys, answers: list[str]) -> tuple[str, list[str]]:
    """Run interactive `init --dev --no-repo` with scripted answers.
    Returns (stdout, prompts asked, in order)."""
    fl_env.run_as(fl_env.dev_app)
    prompts: list[str] = []
    it = iter(answers)

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(it, "")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    args = cli.build_parser().parse_args(["init", "--dev", "--no-repo", "--skip-arch-check"])
    assert cli._cmd_init(args) == 0
    return capsys.readouterr().out, prompts


def test_init_asks_kind_right_after_each_path(fl_env, monkeypatch, capsys):
    _, prompts = _run_init(fl_env, monkeypatch, capsys, [str(fl_env.dev_alias), "", ""])
    dev_prompts = [p for p in prompts if "checkout path" in p or "kind" in p]
    assert ["path" in dev_prompts[0], "kind" in dev_prompts[1], "path" in dev_prompts[2]] == [True] * 3
    assert "[dev-build]" in dev_prompts[1]          # .app path defaults to dev-build
    cfg = cfgmod.load_config()
    assert cfg["default_root"] == str(fl_env.dev_alias)


def test_init_kind_defaults_to_dev_source_for_checkout(fl_env, monkeypatch, capsys):
    checkout = fl_env.tmp / "SSD" / "checkouts" / "slate"
    _, prompts = _run_init(fl_env, monkeypatch, capsys, [str(checkout), "", ""])
    kind_prompt = next(p for p in prompts if "kind" in p)
    assert "[dev-source]" in kind_prompt


def test_init_venv_label_says_where_it_came_from(fl_env, monkeypatch, capsys):
    out, _ = _run_init(fl_env, monkeypatch, capsys, [str(fl_env.dev_alias), "", ""])
    assert "derived" not in out
    assert f"app-script venv (from target build): {fl_env.dev_venv}" in out


@pytest.mark.parametrize("cmd", [
    "/Applications/Baselight/7.0.1/Baselight-7.0.1.app/Contents/MacOS/Baselight",
    "/Volumes/SSD/x/Daylight-7.0.4.unknown.app/Contents/MacOS/Daylight",
    "./MacOS/Daylight",                       # launched from inside Contents/
])
def test_finds_gui_for_app_script_log(cmd, monkeypatch):
    import subprocess
    ps = f" 111 /usr/sbin/cfprefsd\n 99 /x/Daylight.app/Contents/bin/fl-supervise\n 4242 {cmd}\n"
    monkeypatch.setattr(app_scripts.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=ps, stderr=""))
    assert app_scripts._gui_baselight_pid() == "4242"
