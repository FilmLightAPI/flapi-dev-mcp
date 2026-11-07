"""The canonical FLAPI enhancements repo — community/official scripts, shaders,
and tools, maintained by FilmLight at github.com/FilmLightAPI/enhancements.

`init` clones it to ~/.flapi-dev-mcp/repo/ as the primary git context source.
The server fast-forwards it (and any other cloned git source) in the background
each time it starts, so new examples arrive without the user doing anything;
`update` does the same on demand. Degrades gracefully offline.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp.config import REPO_DIR

PULL_TIMEOUT = 60          # seconds per source for the startup pull
NO_PULL_ENV = "FLAPI_DEV_MCP_NO_PULL"

REPO_URL = "https://github.com/FilmLightAPI/enhancements.git"


def _run(args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    # Never prompt for credentials (it would hang), never read our stdin (the
    # MCP's stdio channel), and capture all output so nothing reaches stdout.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          env=env, stdin=subprocess.DEVNULL)


def is_cloned(dest: Path = REPO_DIR) -> bool:
    return (Path(dest) / ".git").is_dir()


def head_commit(dest: Path = REPO_DIR) -> str | None:
    if not is_cloned(dest):
        return None
    try:
        r = _run(["git", "-C", str(dest), "rev-parse", "--short", "HEAD"], timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None


def clone_or_update(url: str = REPO_URL, dest: Path = REPO_DIR,
                    timeout: float | None = None) -> dict:
    """Clone the repo if absent, else fast-forward pull. Never raises."""
    dest = Path(dest)
    action = "pull" if is_cloned(dest) else "clone"
    try:
        if action == "pull":
            # -c pull.rebase=false guards against a broken/deprecated global git
            # config (e.g. pull.rebase=preserve) that would otherwise fail the pull.
            r = _run(["git", "-C", str(dest), "-c", "pull.rebase=false", "pull", "--ff-only"],
                     timeout)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            r = _run(["git", "clone", url, str(dest)], timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return {"action": action, "ok": False, "url": url, "path": str(dest),
                "commit": head_commit(dest), "message": str(e)[:500]}
    return {
        "action": action,
        "ok": r.returncode == 0,
        "url": url,
        "path": str(dest),
        "commit": head_commit(dest),
        "message": (r.stderr or r.stdout).strip()[:500],
    }


def _cloned_git_sources() -> list[Path]:
    cfg = cfgmod.load_config() or {}
    paths = [Path(os.path.expanduser(s.get("path", ""))) for s in cfg.get("sources", [])
             if s.get("type") == "git" and s.get("enabled", True)]
    return [p for p in paths if is_cloned(p)]


def pull_sources_in_background(timeout: float = PULL_TIMEOUT) -> threading.Thread | None:
    """Fast-forward every enabled, already-cloned git source in a daemon thread.

    Called as the server starts. It never blocks startup, never raises, never
    clones (that's init's job) and never writes to stdout. Search reads files
    fresh on every query, so pulled examples are usable as soon as they arrive.
    Set FLAPI_DEV_MCP_NO_PULL=1 to turn it off."""
    if os.environ.get(NO_PULL_ENV):
        return None
    paths = _cloned_git_sources()
    if not paths:
        return None

    def work() -> None:
        for p in paths:
            try:
                clone_or_update(dest=p, timeout=timeout)
            except Exception:       # a background pull must never take the server down
                pass

    t = threading.Thread(target=work, name="flapi-dev-mcp-pull", daemon=True)
    t.start()
    return t
