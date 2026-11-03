"""Path contract: with BOTH a release and a dev build registered, every tool that
returns a path must point inside the targeted build (or its own venv). Catches
mis-paths and silent fallbacks to the other build, for each target in turn."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from flapi_dev_mcp import app_scripts, report, schema, server, venvs
from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS .app layout")


def _inside(path, base: Path) -> bool:
    return path is not None and Path(path).resolve().is_relative_to(base.resolve())


@pytest.fixture(params=["release", "dev"])
def target(request, fl_env):
    """Init with both builds registered and `param` running; return what it should target."""
    if request.param == "dev":
        fl_env.run_as(fl_env.dev_app)
        app, venv, version = fl_env.dev_app, fl_env.dev_venv, "7.0.4.unknown"
    else:
        fl_env.run_as(fl_env.rel_app, kind="release")
        app, venv, version = fl_env.rel_app, fl_env.rel_venv, "7.0.1.25379"
    cfg = cfgmod.build_config(disc.discover(),
                              dev_roots=[(str(fl_env.dev_alias), "dev-build", "slate")])
    cfgmod.save_config(cfg)
    return type("T", (), {"kind": request.param, "app": app, "venv": venv,
                          "version": version, "env": fl_env})


def test_config_paths(target):
    cfg = cfgmod.load_config()
    assert _inside(disc.LAYOUT.resolve_base(Path(cfg["default_root"])), target.app)
    assert cfg["baselight"]["active_venv"] == str(target.venv)
    local = [s["path"] for s in cfg["sources"] if s["type"] == "local"]
    assert local and all(_inside(p, target.app) for p in local)


def test_standalone_paths(target, tmp_path):
    layout = venvs.default_layout()
    assert layout.version == target.version
    assert _inside(layout.wheel, target.app)
    assert _inside(layout.flapid, target.app)
    assert venvs.resolve_venv_dir(str(tmp_path)) == tmp_path.resolve() / ".venv"


def test_docs_and_schema_paths(target):
    assert _inside(schema.active_schema_path(), target.app)
    layout = venvs.default_layout()
    assert _inside(layout.docs_html, target.app)
    assert _inside(layout.examples, target.app)


def test_app_script_paths(target):
    assert app_scripts.managed_venv() == target.venv
    assert _inside(app_scripts._fl_setup_scripts(), target.app)
    r = app_scripts.check_app_script_readiness("both")
    assert r["managed_venv"] == str(target.venv)
    assert r["managed_venv_python"] == str(target.venv / "bin" / "python")


def test_status_and_environment_report_target(target):
    st = report.gather_status()
    assert st["default_version"] == target.version
    assert st["venv"] == str(target.venv)
    full = server.flapi_status()
    assert full["venv"] == str(target.venv)
    assert any(b["product"] for b in full["installed_builds"])


@pytest.fixture
def dev_target(fl_env):
    fl_env.run_as(fl_env.dev_app)
    cfgmod.save_config(cfgmod.build_config(
        disc.discover(), dev_roots=[(str(fl_env.dev_alias), "dev-build", "slate")]))
    return fl_env


def test_missing_target_schema_does_not_use_other_build(dev_target):
    (dev_target.dev_app / "Contents/share/flapi/schema/schema.json").unlink()
    assert not _inside(schema.active_schema_path(), dev_target.rel_app)


def test_missing_target_wheel_does_not_use_other_build(dev_target):
    for w in (dev_target.dev_app / "Contents/share/flapi/python").glob("*.whl"):
        w.unlink()
    layout = venvs.default_layout()
    assert layout is None or not _inside(layout.wheel, dev_target.rel_app)


def test_missing_target_setup_script_does_not_use_other_build(dev_target):
    (dev_target.dev_app / "Contents/bin/fl-setup-flapi-scripts").unlink()
    assert not _inside(app_scripts._fl_setup_scripts(), dev_target.rel_app)
    assert app_scripts.managed_venv() != dev_target.rel_venv
