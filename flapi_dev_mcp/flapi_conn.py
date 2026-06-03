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

    ready = bool(env.get("ok") and flapid.get("connected"))
    remedies = []
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
        "remedies": remedies,
    }
