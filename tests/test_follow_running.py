"""The tools follow the build serving flapid (Victor's bug: with Baselight
configured, Daylight work silently got Baselight's wheel). Covers both
directions, the remote-host exception, and stale-wheel reinstall."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from flapi_dev_mcp import app_scripts, schema, search, venvs
from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app layout")


def _inside(p, base: Path) -> bool:
    return p is not None and Path(p).resolve().is_relative_to(base.resolve())


def _configure(env, target: str, host: str = "localhost") -> None:
    """Save a config targeting `target` ('release' or 'dev'), with both builds registered."""
    env.run_as(env.rel_app if target == "release" else env.dev_app,
               kind="release" if target == "release" else "dev-build")
    cfg = cfgmod.build_config(disc.discover(), flapid_host=host,
                              dev_roots=[(str(env.dev_alias), "dev-build", "slate")])
    cfgmod.save_config(cfg)


def _assert_uses(app: Path, venv: Path):
    layout = venvs.default_layout()
    assert _inside(layout.wheel, app)
    assert _inside(schema.active_schema_path(), app)
    assert app_scripts.managed_venv() == venv
    bundled = [s["path"] for s in search._enabled_sources()
               if str(s["path"]).endswith("/share/flapi/examples/python")]
    assert len(bundled) == 1 and _inside(bundled[0], app)


@pytest.mark.parametrize("configured,running", [("release", "dev"), ("dev", "release")])
def test_tools_follow_the_running_build(fl_env, configured, running):
    _configure(fl_env, configured)
    if running == "dev":
        fl_env.run_as(fl_env.dev_app)
        _assert_uses(fl_env.dev_app, fl_env.dev_venv)
    else:
        fl_env.run_as(fl_env.rel_app, kind="release")
        _assert_uses(fl_env.rel_app, fl_env.rel_venv)
    assert cfgmod.target_layout()[1] == "running"


def test_nothing_running_uses_configured_target(fl_env):
    _configure(fl_env, "dev")
    fl_env.run_as(None)
    _assert_uses(fl_env.dev_app, fl_env.dev_venv)
    assert cfgmod.target_layout()[1] == "config"


def test_remote_host_ignores_the_local_build(fl_env):
    _configure(fl_env, "release", host="bl-master.local")
    fl_env.run_as(fl_env.dev_app)          # something else runs locally
    assert cfgmod.target_layout()[1] == "config"
    assert _inside(venvs.default_layout().wheel, fl_env.rel_app)


def test_stale_wheel_in_project_venv_is_replaced(fl_env, monkeypatch, tmp_path):
    # The project venv was built against release 7.0.1; dev 7.0.4 is now running.
    _configure(fl_env, "release")
    fl_env.run_as(fl_env.dev_app)
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    monkeypatch.setattr(venvs, "_import_check", lambda v: {"ok": True, "detail": ""})
    monkeypatch.setattr(venvs, "_installed_wheel_version", lambda v: "7.0.1.25379")
    pip_calls = []
    def fake_run(args, **kw):
        pip_calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    monkeypatch.setattr(venvs.subprocess, "run", fake_run)
    r = venvs.setup_standalone_env(str(tmp_path))
    assert r["reinstalled_stale_wheel"] is True and r["product"] == "daylight"
    installed = [a for a in pip_calls if "install" in a]
    assert installed and installed[-1][-1].endswith("filmlightapi-7.0.4.99999-py3-none-any.whl")
