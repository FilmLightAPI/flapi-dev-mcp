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
import time
import urllib.request
from pathlib import Path

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc

# FilmLight writes per-process logs here; `/vol/.support/log` is the canonical
# view (the <host>-flapid symlink there points at the live dir).
LOG_DIRS = [Path("/vol/.support/log"), disc.DATA_ROOT / "log"]
RELOAD_PORT = 1984  # flapid HTTP port (server-script reload)
APP_PORT = 1985     # running app's HTTP port (UI-script reload)
MANUAL_RELOAD = "Views > Scripts > (gear) > Reload Scripts"


def _config() -> dict:
    return cfgmod.load_config() or {}


def _fl_setup_scripts() -> Path | None:
    """The target build's fl-setup-flapi-scripts (running build, else configured).
    Never another build's copy: a dev build keeps its venv inside its own .app."""
    layout, _ = cfgmod.target_layout()
    if layout is not None:
        return layout.setup_scripts
    if cfgmod.load_config() is None:
        return next((br.setup_scripts for br in disc.discover().release_roots
                     if br.setup_scripts), None)
    return None


def _venv_via_fl_setup() -> Path | None:
    """Authoritative managed-venv path via `fl-setup-flapi-scripts -e`."""
    return disc.fl_setup_venv(_fl_setup_scripts())


def managed_venv() -> Path | None:
    """The Baselight-managed venv app scripts run in.

    Primary: ask `fl-setup-flapi-scripts -e` (authoritative, no prefs needed).
    Fallbacks: the cached config `active_venv`, then derive from prefs + major.
    Returns an existing venv dir, else the best-known intended path (so callers
    can report "not created yet").
    """
    intended = _venv_via_fl_setup()
    if intended is not None:
        # The build named its venv. Trust it even if not created yet, so a
        # missing dev-build venv reports "create it" instead of silently
        # falling back to another build's (e.g. the shared release) venv.
        return intended

    cfg = _config()
    bl = cfg.get("baselight", {})
    av = bl.get("active_venv")
    if av and (Path(av) / "bin" / "python").exists():
        return Path(av)

    dr = disc.discover_data_root()
    default = cfg.get("default_root")
    major = None
    for r in cfg.get("baselight_roots", []):
        if r.get("path") == default:
            major = disc.baselight_major(r.get("version"))
            break
    derived = disc.resolve_venv(dr.python_dir, dr.python_minor, major)
    # Prefer the script's intended path (even if not yet created) over a None derive,
    # so readiness can point at the right place to create.
    return derived or intended


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
        remedies.append("No FLAPI venv yet (or `import flapi` fails). Create it: run "
                        "`fl-setup-flapi-scripts --create` (headless, builds it), or launch "
                        "Baselight once. Optional: set the Python in Baselight Preferences > "
                        "Advanced > API Server first to pin a version.")
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
            "4. Reload: reload_app_scripts(kind='ui' or 'server'). It confirms the reload really "
            "happened. If it returns restarted=false, ask the user to reload via Views > Scripts > "
            "(gear) > Reload Scripts. For a UI script, the user then clicks the menu item.",
            "5. Verify: UI/app scripts → get_app_script_log (the GUI's plugins.log; catches load "
            "errors too). If it says this build doesn't write that log, have the script write its "
            "own log file and read that. SERVER scripts → get_flapi_log (flapid console). Iterate.",
        ],
    }


def _plugin_pids(kind: str) -> set[str]:
    """PIDs of the Python interpreter that runs app scripts of this kind
    (`flapi-plugins.py app` for UI scripts, `... server` for server scripts).
    A reload that worked replaces it with a new process."""
    try:
        r = subprocess.run(["ps", "-Ao", "pid=,command="], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return set()
    word = "app" if kind == "ui" else "server"
    return {ln.split(None, 1)[0] for ln in r.stdout.splitlines()
            if re.search(rf"flapi-plugins\.py {word}\b", ln)}


def reload_app_scripts(kind: str = "ui", host: str = "localhost", port: int = 0,
                       timeout: int = 12, wait: float = 15.0) -> dict:
    """Reload app scripts, the same as the "Reload Scripts" button, and check it worked.

    kind 'ui' asks the running app (port 1985), kind 'server' asks flapid (1984).
    On this machine it then checks the script interpreter really restarted.
    Some builds (seen on Baselight 7.0.1) accept the request but don't reload
    UI scripts, so `restarted: false` means: ask the user to reload by hand.
    """
    kind = "server" if kind == "server" else "ui"
    port = port or (APP_PORT if kind == "ui" else RELOAD_PORT)
    url = f"http://{host}:{port}/reload-scripts"
    local = host in ("localhost", "127.0.0.1")
    before = _plugin_pids(kind) if local else set()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            status, body = r.status, r.read().decode(errors="replace").strip()
    except Exception as e:
        return {"ok": False, "kind": kind, "url": url, "error": str(e)[:300],
                "action": f"ask the user to reload via {MANUAL_RELOAD}"}
    out = {"ok": status == 200, "kind": kind, "status": status, "body": body, "url": url}
    if not local:
        out["restarted"] = None
        out["note"] = "remote host: can't confirm the reload from here"
        return out
    deadline = time.time() + wait
    after = before
    while time.time() < deadline:
        after = _plugin_pids(kind)
        if after and after != before:
            break
        time.sleep(1)
    out["restarted"] = bool(after) and after != before
    if not out["restarted"]:
        out["action"] = (f"This build accepted the reload but didn't restart its {kind} scripts. "
                         f"Ask the user to reload via {MANUAL_RELOAD}, then check the result.")
    return out


def _current_log_file() -> Path | None:
    """The LIVE flapid (server-script) console log, found dynamically.

    Per-process logs are `<host>-<proc>-<rand>/console.txt` (ephemeral suffixes).
    We gather every `*flapid*` entry across the log dirs, resolving the
    `<host>-flapid` symlinks to their live dirs, and return the most recently
    MODIFIED console.txt — i.e. the one actively being written. Never hardcodes a
    suffix and won't return a stale/other-host log. (flapid = server scripts only;
    app/UI output is in plugins.log, see get_app_script_log.)
    """
    candidates: dict[str, Path] = {}
    for base in LOG_DIRS:
        if not base.is_dir():
            continue
        for entry in base.glob("*flapid*"):
            try:
                real = entry.resolve()
            except OSError:
                continue
            console = real / "console.txt" if real.is_dir() else real
            if console.is_file():
                candidates[str(console)] = console  # dedupe symlink+dir → same file
    if not candidates:
        return None
    return max(candidates.values(), key=lambda f: f.stat().st_mtime)


def get_flapi_log(lines: int = 80) -> dict:
    """Tail the current FLAPI/flapid log — where app-script `print(flush=True)`
    output and load/parse tracebacks land. Use after reloading/running an app
    script to see what happened."""
    f = _current_log_file()
    if f is None:
        return {"ok": False, "error": f"no flapid log found under {LOG_DIRS}"}
    try:
        text = f.read_text(errors="replace")
    except OSError as e:
        return {"ok": False, "log": str(f), "error": str(e)}
    tail = text.splitlines()[-lines:]
    return {"ok": True, "log": str(f), "lines": len(tail), "text": "\n".join(tail)}


def _gui_baselight_pid() -> str | None:
    """PID of the running Baselight or Daylight GUI desktop app (runs app scripts)."""
    try:
        r = subprocess.run(["ps", "-Ao", "pid=,comm="], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in r.stdout.splitlines():
        parts = line.strip().split(None, 1)
        # Match `MacOS/<Product>` so a relative launch (`./MacOS/Daylight`
        # from inside Contents/, common for dev builds) is found too.
        if len(parts) == 2 and re.search(r"(^|/)MacOS/(Baselight|Daylight)$", parts[1]):
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
        return {"ok": False, "error": "no running Baselight/Daylight GUI found — app scripts (and "
                                       "their log) need the desktop app running"}
    td = _fltmpdir(pid)
    if not td:
        return {"ok": False, "error": f"could not read FLTMPDIR from Baselight pid {pid}"}
    log = Path(td) / "plugins.log"
    if not Path(td).is_dir():
        # Seen on Baselight 7.0.1: the app names a log folder it never creates,
        # so script output and load errors aren't written anywhere readable.
        return {"ok": False, "log": str(log), "log_available": False,
                "error": "This build doesn't write an app-script log (its log folder was never "
                         "created). Have the script also append its output to its own log file, "
                         "e.g. ~/.flapi-dev-mcp/logs/<script>.log, and read that. To confirm a "
                         "UI script loaded, ask the user whether its menu item appears."}
    if not log.is_file():
        return {"ok": False, "log": str(log),
                "error": "plugins.log not created yet. It appears once an app script loads "
                         "(deploy a script and reload, then check again)"}
    try:
        text = log.read_text(errors="replace")
    except OSError as e:
        return {"ok": False, "log": str(log), "error": str(e)}
    tail = text.splitlines()[-lines:]
    return {"ok": True, "log": str(log), "lines": len(tail), "text": "\n".join(tail)}


def create_managed_venv() -> dict:
    """Build/update Baselight's managed app-script venv via `fl-setup-flapi-scripts
    --create` (no sudo). Use when the venv doesn't exist yet."""
    fss = _fl_setup_scripts()
    if not fss or not Path(fss).exists():
        return {"ok": False, "error": "fl-setup-flapi-scripts not found in the target build"}
    try:
        r = subprocess.run([str(fss), "--create"], capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e)[:300]}
    venv = _venv_via_fl_setup()
    return {
        "ok": r.returncode == 0,
        "venv": str(venv) if venv else None,
        "log": (r.stdout + r.stderr).strip()[-1500:],
    }


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
