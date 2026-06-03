"""Config file handling for ~/.flapi-dev-mcp/config.json.

Builds the config from discovery results and persists it. The shape mirrors the
"config.json shape" section of CLAUDE.md: a `baselight` data-root block, a
generalized `baselight_roots` list, and a generalized `sources` list.
"""

from __future__ import annotations

import json
from pathlib import Path

from flapi_dev_mcp.discovery import (
    APPS_DIR,
    DATA_ROOT,
    Discovery,
    baselight_major,
    resolve_venv,
)

CONFIG_DIR = Path.home() / ".flapi-dev-mcp"
REPO_DIR = CONFIG_DIR / "repo"
CONFIG_PATH = CONFIG_DIR / "config.json"


def load_config() -> dict | None:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def save_config(cfg: dict) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    return CONFIG_PATH


def _release_root_path(version_dir: Path) -> str:
    """Prefer the stable `Current` symlink so the config survives upgrades."""
    current = APPS_DIR / "Current"
    if current.is_symlink() and current.resolve() == version_dir.resolve():
        return str(current)
    return str(version_dir)


def build_config(
    disc: Discovery,
    *,
    flapid_host: str = "localhost",
    dev_roots: list[tuple[str, str, str | None]] | None = None,  # (path, kind, label)
    extra_sources: list[str] | None = None,
) -> dict:
    dr = disc.data_root

    baselight_roots: list[dict] = []
    for br in disc.release_roots:
        baselight_roots.append({
            "kind": "release",
            "path": _release_root_path(br.path),
            "version": br.version,
            "enabled": True,
        })
    for path, kind, label in (dev_roots or []):
        entry = {"kind": kind, "path": path, "enabled": True}
        if label:
            entry["label"] = label
        baselight_roots.append(entry)

    default_root = baselight_roots[0] if baselight_roots else None
    default_root_path = default_root["path"] if default_root else None

    # The venv depends on which build we target: <python-minor>-v<baselight-major>-venv.
    default_major = baselight_major(default_root.get("version")) if default_root else None
    active_venv = resolve_venv(dr.python_dir, dr.python_minor, default_major)

    # Context sources: bundled examples from the default release root, plus extras.
    sources: list[dict] = []
    for br in disc.release_roots:
        if br.examples is not None:
            sources.append({"type": "local", "path": str(br.examples), "enabled": True})
            break
    for path in (extra_sources or []):
        sources.append({"type": "local", "path": path, "enabled": True})

    return {
        "platform": "macos",
        "language": "python",
        "data_root": str(DATA_ROOT),
        "flapid_host": flapid_host,
        "baselight": {
            "ui_scripts_dir": str(dr.ui_scripts_dir) if dr.ui_scripts_dir else None,
            "server_scripts_dir": str(dr.server_scripts_dir) if dr.server_scripts_dir else None,
            "site_prefs": str(dr.site_prefs) if dr.site_prefs else None,
            "flapi_python_path": dr.flapi_python_path,
            "active_venv": str(active_venv) if active_venv else None,
        },
        "baselight_roots": baselight_roots,
        "default_root": default_root_path,
        "sources": sources,
    }
