"""The MCP-owned standalone venv for FLAPI scripts that run outside Baselight.

Baselight owns the app-script venvs (under …/FilmLight/python); the MCP owns a
separate venv per target build at ~/.flapi-dev-mcp/venvs/<version>/, built from
the same base Python Baselight uses, with the build-matching `filmlightapi`
wheel installed. The two never touch. Backs setup_standalone_env() and
install_dependencies().
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc

VENVS_DIR = cfgmod.CONFIG_DIR / "venvs"


def _config() -> dict:
    return cfgmod.load_config() or {}


def default_layout() -> disc.BuildRoot | None:
    """Resolve the layout (wheel, version, …) of the configured default build root."""
    cfg = _config()
    default = cfg.get("default_root")
    roots = cfg.get("baselight_roots", [])
    ordered = sorted(roots, key=lambda r: r.get("path") != default)  # default first
    for r in ordered:
        layout = disc.resolve_layout(Path(r["path"]), r.get("kind", "release"), r.get("label"))
        if layout.version:
            return layout
    return None


def venv_path(version: str) -> Path:
    return VENVS_DIR / version


def resolve_venv_dir(project_dir: str = "", version: str = "") -> Path:
    """Per-project `.venv` when a project dir is given (preferred), else the
    shared per-build venv under ~/.flapi-dev-mcp/venvs/<version> (fallback)."""
    if project_dir:
        return Path(project_dir).expanduser().resolve() / ".venv"
    return VENVS_DIR / version


def venv_python(venv: Path) -> Path:
    return venv / "bin" / "python"


def _import_check(venv: Path) -> dict:
    r = subprocess.run(
        [str(venv_python(venv)), "-c", "import flapi; print(flapi.__file__)"],
        capture_output=True, text=True,
    )
    return {"ok": r.returncode == 0, "detail": (r.stdout or r.stderr).strip()[:300]}


def setup_standalone_env(project_dir: str = "", reinstall_wheel: bool = False) -> dict:
    """Create the standalone venv (if absent) and install the filmlightapi wheel.

    With project_dir, the venv is created at <project_dir>/.venv (preferred —
    self-contained, isolated per project). Without it, a shared per-build venv
    under ~/.flapi-dev-mcp/venvs/<version> is used (fallback).
    """
    layout = default_layout()
    if layout is None:
        return {"ok": False, "error": "no usable build root; run `flapi-dev-mcp init`"}
    if not layout.wheel:
        return {"ok": False, "error": f"no filmlightapi wheel found in build root {layout.app}"}

    version = layout.version
    venv = resolve_venv_dir(project_dir, version)
    base_python = _config().get("baselight", {}).get("flapi_python_path") or sys.executable

    created = False
    if not venv_python(venv).exists():
        VENVS_DIR.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([base_python, "-m", "venv", str(venv)], capture_output=True, text=True)
        if r.returncode != 0:
            return {"ok": False, "error": "venv creation failed", "detail": r.stderr[:500]}
        created = True

    imp = _import_check(venv)
    if created or reinstall_wheel or not imp["ok"]:
        r = subprocess.run(
            [str(venv_python(venv)), "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", str(layout.wheel)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return {"ok": False, "error": "wheel install failed", "detail": r.stderr[:500],
                    "venv": str(venv)}
        imp = _import_check(venv)

    return {
        "ok": imp["ok"],
        "version": version,
        "base_python": base_python,
        "venv": str(venv),
        "venv_python": str(venv_python(venv)),
        "mode": "project" if project_dir else "shared",
        "created": created,
        "wheel": str(layout.wheel),
        "import_flapi": imp,
    }


def install_dependencies(packages: list[str], project_dir: str = "") -> dict:
    """Pip-install extra packages into the standalone venv (sets it up first if needed)."""
    layout = default_layout()
    if layout is None:
        return {"ok": False, "error": "no usable build root; run `flapi-dev-mcp init`"}
    venv = resolve_venv_dir(project_dir, layout.version)
    if not venv_python(venv).exists():
        setup = setup_standalone_env(project_dir)
        if not setup["ok"]:
            return {"ok": False, "error": "standalone venv setup failed", "setup": setup}
    if not packages:
        return {"ok": True, "packages": [], "note": "no packages requested", "venv": str(venv)}
    r = subprocess.run(
        [str(venv_python(venv)), "-m", "pip", "install", "--disable-pip-version-check", *packages],
        capture_output=True, text=True,
    )
    return {
        "ok": r.returncode == 0,
        "packages": packages,
        "venv": str(venv),
        "log": (r.stdout + r.stderr).strip()[-1500:],
    }
