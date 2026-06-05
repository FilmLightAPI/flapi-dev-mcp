"""flapid connectivity + standalone readiness.

Probes a real FLAPI connection from the standalone venv (so it exercises the
actual installed `flapi`), with a timeout. For localhost the auth token is
resolved automatically; remote hosts need a token from `fl-setup-flapi-token`.
Backs check_flapid() and check_standalone_readiness().
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import venvs

# macOS token location (per FLAPI docs).
TOKEN_PATH = Path.home() / "Library" / "Preferences" / "FilmLight" / "flapi-token"

# Connect, list jobs, close — all in the venv subprocess. Host is argv[1].
_PROBE = r"""
import json, sys
host = sys.argv[1]
try:
    import flapi
    conn = flapi.Connection(host)
    conn.connect()
    try:
        jobs = conn.JobManager.get_jobs(host)
    except Exception as e:
        jobs = None
    out = {"connected": True, "host": host, "jobs": jobs}
    try:
        conn.close()
    except Exception:
        pass
    print(json.dumps(out))
except Exception as e:
    print(json.dumps({"connected": False, "host": host,
                      "error": type(e).__name__ + ": " + str(e)[:300]}))
"""


# Connect to the RUNNING app's API server (default :1985) and report live state.
# argv: port, username.
_APP_PROBE = r"""
import json, sys, getpass
port = int(sys.argv[1])
user = sys.argv[2] or getpass.getuser()
host = sys.argv[3] if len(sys.argv) > 3 else "localhost"
try:
    import flapi
    conn = flapi.Connection(host, port, user)
    conn.connect()
    app = conn.Application.get()
    try:
        scene = app.get_current_scene_name()
    except Exception:
        scene = None
    try:
        open_scenes = app.get_open_scene_names()
    except Exception:
        open_scenes = None
    out = {"connected": True, "port": port, "username": user,
           "current_scene": scene, "open_scenes": open_scenes,
           "scene_open": bool(scene)}
    try:
        conn.close()
    except Exception:
        pass
    print(json.dumps(out))
except Exception as e:
    print(json.dumps({"connected": False, "port": port, "username": user,
                      "error": type(e).__name__ + ": " + str(e)[:300]}))
"""


def check_app_connection(port: int = 1985, username: str = "", host: str = "localhost",
                         project_dir: str = "", timeout: int = 15) -> dict:
    """Probe a RUNNING Baselight app's API server (the live-app path; default localhost:1985)."""
    import getpass
    user = username or getpass.getuser()
    layout = venvs.default_layout()
    if layout is None:
        return {"connected": False, "port": port, "host": host, "error": "no build root; run `flapi-dev-mcp init`"}
    venv = venvs.resolve_venv_dir(project_dir, layout.version)
    py = venvs.venv_python(venv)
    if not py.exists():
        return {"connected": False, "port": port, "host": host,
                "error": "standalone venv not set up; call setup_standalone_env first"}
    try:
        r = subprocess.run([str(py), "-c", _APP_PROBE, str(port), user, host or "localhost"],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"connected": False, "port": port, "error": f"timed out after {timeout}s"}
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"connected": False, "port": port,
                "error": (r.stderr or r.stdout).strip()[:300] or "no output"}

    if not out.get("connected"):
        err = out.get("error", "")
        if "No module named 'flapi'" in err or "ModuleNotFoundError" in err:
            out["remedy"] = ("the standalone venv can't import flapi — run "
                             "setup_standalone_env(project_dir) first, then retry.")
        else:
            out["remedy"] = (
                f"nothing answering FLAPI on :{port}. The running app serves its API on this "
                f"port (default 1985, set in Baselight Prefs > Advanced > API Server). Make sure "
                f"Baselight is running and the API server is enabled; it binds the port on startup."
            )
    elif not out.get("scene_open"):
        out["remedy"] = ("connected to the app, but no scene is open. Open a scene in Baselight "
                         "for live-session work (current scene / cursor / live thumbnails).")
    else:
        h = host or "localhost"
        local = h in ("localhost", "127.0.0.1")
        out["connect_idiom"] = (f'flapi.Connection("{h}", {port})  # user+token auto-resolved locally'
                                if local else f'flapi.Connection("{h}", {port}, "{user}")')
        out["thumbnail_fetch"] = (f"ThumbnailManager.get_poster_uri(shot, opts) returns a relative "
                                  f"URI; GET http://{h}:{port}<uri> for the image bytes.")
    return out


def connection_selector(choice: str = "", host: str = "", port: int = 0,
                        username: str = "", project_dir: str = "") -> dict:
    """Connection-type selector. No choice -> a menu of options with live status
    (the agent asks the user which they want). With a choice -> tests that one and
    returns a ready-to-paste, verified snippet (connect + close)."""
    import getpass
    choice = (choice or "").strip().lower()
    user = username or getpass.getuser()

    if not choice:
        flapid = check_flapid(host or None, project_dir)
        app = check_app_connection(port or 1985, user, "localhost", project_dir)
        layout = venvs.default_layout()
        return {
            "mode": "discover",
            "options": [
                {"type": "flapid",
                 "desc": "Headless daemon (:1984). Opens scenes by name; the app need not be "
                         "running. Local auto-auth; remote needs a token.",
                 "reachable": flapid.get("connected"), "jobs": flapid.get("jobs"),
                 "example": 'flapi.Connection("localhost")'},
                {"type": "app",
                 "desc": "The live running app (:1985). Gives Application, the current OPEN scene, "
                         "cursor/viewing state, and live thumbnails. Needs Baselight running with "
                         "a scene open.",
                 "reachable": app.get("connected"), "scene_open": app.get("current_scene"),
                 "example": 'flapi.Connection("localhost", 1985)  # user+token auto-resolved locally'},
                {"type": "launch",
                 "desc": "Spawn a private flapid from the build — fully headless, no running "
                         "service needed.",
                 "available": bool(layout and layout.flapid),
                 "example": 'conn = flapi.Connection(); conn.launch(); conn.connect()'},
                {"type": "remote",
                 "desc": "Connect to ANOTHER machine's flapid (1984) or running app (1985). Not "
                         "probed here (no host to test) — it's a build-time option. The user must "
                         "supply hostname + username + a token (created via fl-setup-flapi-token on "
                         "that host). Use for e.g. 'check if BL is running / what version on host X'.",
                 "requires": ["hostname", "username", "token"],
                 "example": 'flapi.Connection("<host>", <port>, "<user>")'},
            ],
            "guidance": ("Pick by task: live/open scene, cursor, or live thumbnails -> 'app'; "
                         "headless batch/render/export/metadata by name -> 'flapid' (or 'launch' "
                         "if no daemon is running); another machine -> 'remote'. Ask the user when "
                         "unclear, then call again with choice= to get the tested snippet."),
        }

    # --- emit: test the chosen connection, return a verified snippet -----------
    if choice == "launch":
        layout = venvs.default_layout()
        return {
            "mode": "emit", "choice": "launch",
            "available": bool(layout and layout.flapid),
            "snippet": ('conn = flapi.Connection()\n'
                        'conn.launch()        # spawns a private flapid from the build\n'
                        'conn.connect()\n'
                        '# ... work ...\n'
                        'conn.close()'),
            "note": "Not live-probed (it spawns a daemon). Use when no flapid is running.",
        }

    if choice == "remote":
        # Build-time option: emit a parameterized snippet + the prerequisites.
        # Do NOT gate on a live connection (the target may be unreachable now, and
        # the token may not be set up locally). Best-effort probe only if a real
        # host was supplied — and report it as informational.
        h = host or "<host>"
        p = port or 1984
        u = username or "<user>"
        is_app = p == 1985
        body = ('app = conn.Application.get()\ninfo = app.get_application_info()\n'
                if is_app else 'info = conn.Application.get_application_info()\n')
        out = {
            "mode": "emit", "choice": "remote",
            "requires": ["hostname", "username", "token"],
            "token_present_locally": auth_token_present(),
            "token_path": str(TOKEN_PATH),
            "note": (f"Remote is not probed. The user supplies host/username, and a token "
                     f"must be created on the target with `fl-setup-flapi-token` (stored at "
                     f"{TOKEN_PATH}). get_application_info() reports the running build/version."),
            "snippet": (f'conn = flapi.Connection("{h}", {p}, "{u}")\n'
                        f'conn.connect()                      # token must exist for {h}\n'
                        f'{body}'
                        f'# ... work ...\n'
                        f'conn.close()'),
        }
        if host:  # concrete host given — informational reachability check, not a gate
            probe = (check_app_connection(p, username, host, project_dir)
                     if is_app else check_flapid(host, project_dir))
            out["probe"] = {"connected": probe.get("connected"), "error": probe.get("error")}
        return out

    if choice == "app":
        # Local live-app. Username/token auto-resolve on localhost, so omit them.
        res = check_app_connection(port or 1985, "", "localhost", project_dir)
        res["mode"] = "emit"; res["choice"] = "app"
        if res.get("connected"):
            res["snippet"] = (f'conn = flapi.Connection("localhost", {port or 1985})\n'
                              f'conn.connect()                      # local: user+token auto-resolved\n'
                              f'app = conn.Application.get()\n'
                              f'scene = app.get_current_scene()\n'
                              f'# ... work ...\n'
                              f'conn.close()')
        return res

    # flapid (and remote-flapid)
    res = check_flapid(host or None, project_dir)
    h = res.get("host", host or "localhost")
    remote = h not in ("localhost", "127.0.0.1", "")
    res["mode"] = "emit"; res["choice"] = choice
    res["snippet"] = (f'conn = flapi.Connection("{h}"'
                      + (f', username="{user}"' if remote else '') + ')\n'
                      f'conn.connect()\n'
                      f'# ... open a scene by path, do work ...\n'
                      f'conn.close()')
    if remote and not auth_token_present():
        res["auth_note"] = f"remote needs a token — run fl-setup-flapi-token on {h} ({TOKEN_PATH})"
    return res


def _host(hostname: str | None) -> str:
    if hostname:
        return hostname
    return (cfgmod.load_config() or {}).get("flapid_host") or "localhost"


def auth_token_present() -> bool:
    return TOKEN_PATH.is_file()


def check_flapid(hostname: str | None = None, project_dir: str = "", timeout: int = 15) -> dict:
    """Attempt a real FLAPI connection from the standalone venv."""
    host = _host(hostname)
    layout = venvs.default_layout()
    if layout is None:
        return {"connected": False, "host": host,
                "error": "no build root; run `flapi-dev-mcp init`"}
    venv = venvs.resolve_venv_dir(project_dir, layout.version)
    py = venvs.venv_python(venv)
    if not py.exists():
        return {"connected": False, "host": host,
                "error": "standalone venv not set up; call setup_standalone_env first"}
    try:
        r = subprocess.run([str(py), "-c", _PROBE, host],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"connected": False, "host": host,
                "error": f"timed out after {timeout}s (flapid not responding?)"}
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"connected": False, "host": host,
                "error": (r.stderr or r.stdout).strip()[:300] or "no output"}


def check_standalone_readiness(hostname: str | None = None, project_dir: str = "") -> dict:
    """Aggregate everything needed to run a standalone script: venv + flapi
    import + flapid connectivity + auth token."""
    host = _host(hostname)
    env = venvs.setup_standalone_env(project_dir)
    flapid = check_flapid(host, project_dir)
    is_local = host in ("localhost", "127.0.0.1", "")
    token_ok = is_local or auth_token_present()

    # Is the build we're targeting (wheel/docs) the same as the one actually
    # serving on :1984? A mismatch means the agent's docs/wheel may not match
    # the live flapid.
    from flapi_dev_mcp import discovery as disc
    targeted = venvs.default_layout()
    targeted_v = targeted.version if targeted else None
    running = disc.detect_running_build() if is_local else None
    running_v = running.version if running else None
    build_match = {
        "targeted": targeted_v,
        "running": running_v,
        "match": (running_v is None) or (running_v == targeted_v),
        "running_app": str(running.app) if running else None,
    }

    ready = bool(env.get("ok") and flapid.get("connected"))
    remedies = []
    if running_v and targeted_v and running_v != targeted_v:
        restart_cmd = (f"sudo {targeted.app}/Contents/bin/fl-service restart flapi"
                       if targeted and targeted.app else "sudo fl-service restart flapi")
        remedies.append(
            f"build mismatch: you chose target {targeted_v} (at init), but the live "
            f"flapid is {running_v} ({running.app}). Two fixes — "
            f"(1) make the server match your target (usual): restart flapid from your "
            f"target build, `{restart_cmd}`, or launch that build's Baselight; "
            f"(2) switch your target to the running build: `flapi-dev-mcp target-running`. "
            f"Until then, docs/wheel are {targeted_v} but the server is {running_v}."
        )
    if not env.get("ok"):
        remedies.append("standalone venv / import flapi failed — see env detail")
    if not flapid.get("connected"):
        remedies.append(
            "flapid not reachable — start Baselight (so flapid runs), or use the "
            "self-contained flapi.Connection().launch() pattern, which spawns a "
            "private flapid from the build."
        )
    if not token_ok:
        remedies.append(f"no auth token for remote host — run fl-setup-flapi-token "
                        f"on {host}, token stored at {TOKEN_PATH}")

    return {
        "ready": ready,
        "host": host,
        "venv": {"ok": env.get("ok"), "venv": env.get("venv"),
                 "import_flapi": env.get("import_flapi")},
        "flapid": flapid,
        "auth": {"local_auto": is_local, "token_present": auth_token_present(), "ok": token_ok},
        "build_match": build_match,
        "remedies": remedies,
    }
