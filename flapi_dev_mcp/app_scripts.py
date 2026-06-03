"""App Scripts support — scripts that run *inside* Baselight.

Unlike standalone scripts (MCP-owned venv), App Scripts run in Baselight's
MANAGED venv and deploy into the directories the app scans (scripts/ for UI,
server-scripts/ for server). So dependencies must go into the managed venv, and
the agent writes the script into the deploy dir; Baselight loads it.

Backs check_app_script_readiness() and install_app_dependencies().
"""

from __future__ import annotations

import os
import subprocess
import urllib.request
from pathlib import Path

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc

LOG_DIR = disc.DATA_ROOT / "log"
RELOAD_PORT = 1984  # the FilmLight app server (flici) HTTP port


def _config() -> dict:
    return cfgmod.load_config() or {}


def managed_venv() -> Path | None:
    """The Baselight-managed venv app scripts run in (from config, or derived)."""
    cfg = _config()
    bl = cfg.get("baselight", {})
    av = bl.get("active_venv")
    if av and (Path(av) / "bin" / "python").exists():
        return Path(av)
    # derive from prefs python + default root major
    dr = disc.discover_data_root()
    default = cfg.get("default_root")
    major = None
    for r in cfg.get("baselight_roots", []):
        if r.get("path") == default:
            major = disc.baselight_major(r.get("version"))
            break
    return disc.resolve_venv(dr.python_dir, dr.python_minor, major)


def _import_flapi(venv: Path) -> dict:
    py = venv / "bin" / "python"
    if not py.exists():
        return {"ok": False, "detail": "venv python missing"}
    r = subprocess.run([str(py), "-c", "import flapi; print(flapi.__file__)"],
                       capture_output=True, text=True)
    return {"ok": r.returncode == 0, "detail": (r.stdout or r.stderr).strip()[:300]}


def _dir_status(path: str | None) -> dict:
    if not path:
        return {"path": None, "exists": False, "writable": False}
    p = Path(path)
    return {"path": str(p), "exists": p.is_dir(),
            "writable": p.is_dir() and os.access(p, os.W_OK)}


def check_app_script_readiness(kind: str = "both") -> dict:
    """Ready to deploy an App Script? Checks managed venv + deploy dirs.

    kind: 'ui' (scripts/), 'server' (server-scripts/), or 'both'.
    """
    cfg = _config()
    bl = cfg.get("baselight", {})
    venv = managed_venv()
    venv_ok = venv is not None and (venv / "bin" / "python").exists()
    imp = _import_flapi(venv) if venv_ok else {"ok": False, "detail": "no managed venv"}

    dirs: dict[str, dict] = {}
    if kind in ("ui", "both"):
        dirs["ui"] = _dir_status(bl.get("ui_scripts_dir"))
    if kind in ("server", "both"):
        dirs["server"] = _dir_status(bl.get("server_scripts_dir"))

    dirs_ok = all(d["exists"] and d["writable"] for d in dirs.values()) if dirs else False
    ready = bool(venv_ok and imp["ok"] and dirs_ok)

    remedies = []
    if not venv_ok or not imp["ok"]:
        remedies.append("Baselight's managed venv missing or `import flapi` fails — "
                        "launch Baselight (it creates the venv) or run `fl-setup-flapi-scripts --create`")
    for name, d in dirs.items():
        if not d["exists"]:
            remedies.append(f"{name} script dir missing: {d['path']}")
        elif not d["writable"]:
            remedies.append(f"{name} script dir not writable: {d['path']}")

    return {
        "ready": ready,
        "kind": kind,
        "managed_venv": str(venv) if venv else None,
        "managed_venv_python": str(venv / "bin" / "python") if venv else None,
        "import_flapi": imp,
        "deploy_dirs": dirs,
        "remedies": remedies,
        "note": "Write the app script into the deploy dir, then load/reload it in Baselight. "
                "Install any extra deps with install_app_dependencies (managed venv).",
    }


def reload_app_scripts(host: str = "localhost", timeout: int = 12) -> dict:
    """Trigger Baselight's "Reload Scripts" action programmatically.

    This is exactly what the Views > Scripts > (gear) > Reload Scripts button
    does: an HTTP GET to http://<host>:1984/reload-scripts, which restarts the
    FLAPI server's Python so newly-deployed/edited app scripts are picked up.
    """
    url = f"http://{host}:{RELOAD_PORT}/reload-scripts"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode(errors="replace").strip()
            return {"ok": r.status == 200, "status": r.status, "body": body, "url": url}
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)[:300],
                "fallback": "run in Terminal: sudo fl-service restart flapi"}


def _current_log_file() -> Path | None:
    """Best-effort: the log carrying flapid/app-script output.

    Logs are per-process `<host>-<proc>-<rand>/console.txt`. We try the
    `<host>-flapid` symlink (file or dir/console.txt); if that's stale, fall
    back to the most-recently-modified `console.txt` one level down.
    """
    if not LOG_DIR.is_dir():
        return None
    for p in LOG_DIR.glob("*-flapid"):
        try:
            real = p.resolve()
        except OSError:
            continue
        if real.is_file():
            return real
        if real.is_dir() and (real / "console.txt").is_file():
            return real / "console.txt"
    consoles = [c for c in LOG_DIR.glob("*/console.txt") if c.is_file()]
    return max(consoles, key=lambda f: f.stat().st_mtime) if consoles else None


def get_flapi_log(lines: int = 80) -> dict:
    """Tail the current FLAPI/flapid log — where app-script `print(flush=True)`
    output and load/parse tracebacks land. Use after reloading/running an app
    script to see what happened."""
    f = _current_log_file()
    if f is None:
        return {"ok": False, "error": f"no flapid log found under {LOG_DIR}"}
    try:
        text = f.read_text(errors="replace")
    except OSError as e:
        return {"ok": False, "log": str(f), "error": str(e)}
    tail = text.splitlines()[-lines:]
    return {"ok": True, "log": str(f), "lines": len(tail), "text": "\n".join(tail)}


def install_app_dependencies(packages: list[str]) -> dict:
    """Pip-install packages into Baselight's MANAGED venv (where app scripts run).

    Distinct from install_dependencies, which targets the standalone venv.
    """
    venv = managed_venv()
    if venv is None or not (venv / "bin" / "python").exists():
        return {"ok": False, "error": "managed venv not found; launch Baselight or run "
                                       "fl-setup-flapi-scripts --create"}
    if not packages:
        return {"ok": True, "packages": [], "note": "no packages requested",
                "managed_venv": str(venv)}
    py = venv / "bin" / "python"
    r = subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", *packages],
                       capture_output=True, text=True)
    return {
        "ok": r.returncode == 0,
        "packages": packages,
        "managed_venv": str(venv),
        "log": (r.stdout + r.stderr).strip()[-1500:],
    }
