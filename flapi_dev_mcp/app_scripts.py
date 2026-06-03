"""App Scripts support — scripts that run *inside* Baselight.

Unlike standalone scripts (MCP-owned venv), App Scripts run in Baselight's
MANAGED venv and deploy into the directories the app scans (scripts/ for UI,
server-scripts/ for server). So dependencies must go into the managed venv, and
the agent writes the script into the deploy dir; Baselight loads it.

Backs check_app_script_readiness() and install_app_dependencies().
"""

from __future__ import annotations

import os
import re
import subprocess
import urllib.request
from pathlib import Path

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc

# FilmLight writes per-process logs here; `/vol/.support/log` is the canonical
# view (the <host>-flapid symlink there points at the live dir).
LOG_DIRS = [Path("/vol/.support/log"), disc.DATA_ROOT / "log"]
RELOAD_PORT = 1984  # flapid HTTP port (server-script reload)


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
        "workflow": [
            "1. Have the script print(..., flush=True) what it does — you can't see return "
            "values, so logging is how you observe it. (Its output + any load traceback go to "
            "the app log, which get_app_script_log tails.)",
            "2. Syntax-check before deploy: managed-venv python `-m py_compile <script>`.",
            "3. Deploy: UI scripts → scripts/, server scripts → server-scripts/. Install extra deps "
            "with install_app_dependencies (managed venv), NOT install_dependencies.",
            "4. Reload: SERVER scripts → reload_app_scripts (flapid :1984). UI scripts → ask the user "
            "to reload via Views > Scripts > (gear) > Reload Scripts, then click the menu item.",
            "5. Verify: UI/app scripts → get_app_script_log (the GUI's plugins.log; catches load "
            "errors too). SERVER scripts → get_flapi_log (flapid console). Iterate.",
        ],
    }


def reload_app_scripts(host: str = "localhost", port: int = RELOAD_PORT, timeout: int = 12) -> dict:
    """Trigger Baselight's "Reload Scripts" action programmatically.

    HTTP GET http://<host>:<port>/reload-scripts. NOTE: app scripts and server
    scripts are served by DIFFERENT servers, each with this endpoint. The app
    API server (UI scripts) uses the `flapi_port_number` pref — normally 1984,
    but if multiple Baselights contend for 1984 the app server falls back to a
    dynamic port. If reload doesn't pick up a UI script, you're likely hitting
    flapid (server scripts) instead; pass the app server's actual port.
    """
    url = f"http://{host}:{port}/reload-scripts"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode(errors="replace").strip()
            return {"ok": r.status == 200, "status": r.status, "body": body, "url": url}
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)[:300],
                "fallback": "run in Terminal: sudo fl-service restart flapi"}


def _current_log_file() -> Path | None:
    """The live flapid (server-script) console log.

    Per-process logs are `<host>-<proc>-<rand>/console.txt`. The `<host>-flapid`
    symlink points at the current dir; failing that, take the most recently
    modified `*flapid*/console.txt`. NOTE: this is flapid = server scripts only;
    app/UI script output is not written here (use the script's self-log).
    """
    for base in LOG_DIRS:
        if not base.is_dir():
            continue
        for p in base.glob("*-flapid"):
            try:
                real = p.resolve()
            except OSError:
                continue
            console = real / "console.txt" if real.is_dir() else real
            if console.is_file():
                return console
        consoles = [d / "console.txt" for d in base.glob("*flapid*")
                    if (d / "console.txt").is_file()]
        if consoles:
            return max(consoles, key=lambda f: f.stat().st_mtime)
    return None


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


def _gui_baselight_pid() -> str | None:
    """PID of the running Baselight GUI desktop app (runs app scripts)."""
    try:
        r = subprocess.run(["ps", "-Ao", "pid=,comm="], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in r.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1].endswith("/Contents/MacOS/Baselight"):
            return parts[0]
    return None


def _fltmpdir(pid: str) -> str | None:
    """Read FLTMPDIR from a process's environment (value may contain spaces)."""
    try:
        r = subprocess.run(["ps", "eww", pid], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"FLTMPDIR=(.*?)(?= [A-Za-z_][A-Za-z0-9_]*=)", r.stdout)
    return m.group(1) if m else None


def get_app_script_log(lines: int = 80) -> dict:
    """Tail the live app-script log — `$FLTMPDIR/plugins.log`, the file the GUI's
    Views > Scripts > (gear) > Open Log File reveals. Captures app-script output
    AND load tracebacks. Resolves FLTMPDIR from the running Baselight GUI."""
    pid = _gui_baselight_pid()
    if pid is None:
        return {"ok": False, "error": "no running Baselight GUI found — app scripts (and "
                                       "their log) need the desktop app running"}
    td = _fltmpdir(pid)
    if not td:
        return {"ok": False, "error": f"could not read FLTMPDIR from Baselight pid {pid}"}
    log = Path(td) / "plugins.log"
    if not log.is_file():
        return {"ok": False, "log": str(log),
                "error": "plugins.log not created yet — it appears once an app script loads "
                         "(deploy a script and reload, then check again)"}
    try:
        text = log.read_text(errors="replace")
    except OSError as e:
        return {"ok": False, "log": str(log), "error": str(e)}
    tail = text.splitlines()[-lines:]
    return {"ok": True, "log": str(log), "lines": len(tail), "text": "\n".join(tail)}


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
