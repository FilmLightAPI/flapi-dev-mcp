"""Live end-to-end install + provisioning, the README flow on the real machine:

    uv tool install <this checkout>  →  flapi-dev-mcp init --yes  →  flapi-dev-mcp status

Runs in a temp HOME and temp uv tool dirs, so your real config and tools are
untouched. Uses whichever build is serving flapid right now, so run it once
with release services up and once with dev services up:

    FLAPI_LIVE=1 FLAPI_DEV_ROOT=<dev .app> .venv/bin/python -m pytest -q tests/live
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not os.environ.get("FLAPI_LIVE"), reason="set FLAPI_LIVE=1")


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    tools, bins = home / "uv-tools", home / "bin"
    env = {**os.environ, "HOME": str(home), "UV_TOOL_DIR": str(tools),
           "UV_TOOL_BIN_DIR": str(bins), "PATH": f"{bins}:{os.environ['PATH']}"}
    r = subprocess.run(["uv", "tool", "install", "--no-cache", str(REPO)],
                       env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    exe = bins / "flapi-dev-mcp"
    assert exe.exists()
    return home, env, exe


def _init(installed) -> tuple[subprocess.CompletedProcess, dict]:
    home, env, exe = installed
    args = [str(exe), "init", "--yes"]
    if os.environ.get("FLAPI_DEV_ROOT"):
        args += ["--dev-root", f"{os.environ['FLAPI_DEV_ROOT']}:dev-build:live"]
    r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=600)
    cfg_path = home / ".flapi-dev-mcp" / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    return r, cfg


def test_install_init_status_target_the_running_build(installed):
    running = disc.detect_running_build()
    assert running is not None, "no flapid running; start services from the build to test"

    r, cfg = _init(installed)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert cfgmod.same_build(cfg["default_root"], running), cfg["default_root"]

    # The venv must be the one the running build itself reports, for the same
    # user: it depends on per-user prefs (e.g. a Python override), so ask under
    # the same HOME init ran with.
    home, env, exe = installed
    out = subprocess.run([str(running.setup_scripts), "-e"], env=env,
                         capture_output=True, text=True).stdout.strip()
    want = Path(out)
    assert cfg["baselight"]["active_venv"] == str(want)
    assert (want / "bin" / "python").exists()
    r2 = subprocess.run([str(want / "bin" / "python"), "-c", "import flapi"],
                        capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr

    # Bundled examples come from the running build, and the repo was cloned.
    local = [s["path"] for s in cfg["sources"] if s["type"] == "local"]
    base = disc.LAYOUT.resolve_base(running.app or running.path).resolve()
    assert local and all(Path(p).resolve().is_relative_to(base) for p in local)
    assert (home / ".flapi-dev-mcp" / "repo" / ".git").is_dir()
    assert "running build matches target" in r.stdout

    st = subprocess.run([str(exe), "status"], env=env, capture_output=True, text=True)
    assert st.returncode == 0, st.stdout + st.stderr


def test_init_is_idempotent(installed):
    r1, cfg1 = _init(installed)
    r2, cfg2 = _init(installed)
    assert r1.returncode == r2.returncode == 0
    assert cfg1 == cfg2
