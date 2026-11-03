"""Config file handling for ~/.flapi-dev-mcp/config.json.

Builds the config from discovery results and persists it. The shape mirrors the
"config.json shape" section of CLAUDE.md: a `baselight` data-root block, a
generalized `baselight_roots` list, and a generalized `sources` list.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from flapi_dev_mcp.discovery import (
    APPS_DIR, DATA_ROOT, LAYOUT, BuildRoot, Discovery, detect_running_build,
    fl_setup_venv, is_supported_version, resolve_layout,
)


def same_build(root_path: str | Path, br: BuildRoot) -> bool:
    """True if a configured root path is the same build as `br`.

    Compares resolved build bases (`<app>/Contents` on macOS), so a root given
    via a symlinked path (e.g. ~/Development → /Volumes/SSD/Development) or as
    the release `Current` symlink still matches the running build."""
    a = LAYOUT.resolve_base(Path(root_path))
    b = LAYOUT.resolve_base(br.app or br.path)
    if a is None or b is None:
        return False
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


_RUNNING_CACHE: dict = {}


def running_build(ttl: float = 10.0) -> "BuildRoot | None":
    """The build serving flapid on this machine, cached briefly (detection
    shells out to ps/lsof, and one tool call can ask several times)."""
    now = time.time()
    if _RUNNING_CACHE and now - _RUNNING_CACHE["t"] < ttl:
        return _RUNNING_CACHE["v"]
    v = detect_running_build()
    _RUNNING_CACHE.update(t=now, v=v)
    return v


def target_layout() -> "tuple[BuildRoot | None, str]":
    """The build every tool should use, and why: ("running", ...) or ("config", ...).

    Only one product can serve flapid on :1984 at a time, so locally the build
    that's actually running is always the right wheel, schema, venv and
    examples, whatever init chose, including after switching between Baselight
    and Daylight or between builds. With a remote flapid_host, or nothing
    running here, the configured default_root is used."""
    cfg = load_config() or {}
    host = cfg.get("flapid_host") or "localhost"
    if host in ("localhost", "127.0.0.1"):
        running = running_build()
        if running is not None and running.wheel is not None and is_supported_version(running.version):
            return running, "running"
    default = cfg.get("default_root")
    r = next((r for r in cfg.get("baselight_roots", []) if r.get("path") == default), None)
    if r is None:
        return None, "config"
    return resolve_layout(Path(r["path"]), r.get("kind", "release"), r.get("label"),
                          r.get("product")), "config"


def _platform_name() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform

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


def _release_root_path(version_dir: Path, product: str) -> str:
    """Prefer the stable "current build" symlink so config survives upgrades.

    Per-product: baselight → e.g. /usr/fl/baselight (Linux) or
    /Applications/Baselight/Current (macOS); daylight → /usr/fl/daylight or
    /Applications/Daylight/Current. Falls back to the versioned dir if the
    product's symlink doesn't point at it."""
    prod = LAYOUT.product_by_name(product)
    if prod:
        current = prod.current_symlink
        try:
            if current.is_symlink() and current.resolve() == version_dir.resolve():
                return str(current)
        except OSError:
            pass
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
            "product": br.product,
            "path": _release_root_path(br.path, br.product),
            "version": br.version,
            "enabled": True,
        })
    for path, kind, label in (dev_roots or []):
        # Resolve product + version up front so a dev root is a first-class
        # default candidate (without a version it never passes the BL7+ check).
        dl = resolve_layout(Path(path), kind, label)
        entry = {"kind": kind, "product": dl.product, "path": path,
                 "version": dl.version, "enabled": True}
        if label:
            entry["label"] = label
        baselight_roots.append(entry)

    # Default-root selection, across products (Baselight + Daylight both
    # possible). Priority:
    #   1. Running product's current symlink target, if BL7+ (matches what
    #      flapid is actually serving right now).
    #   2. Any product's current-symlink target that is BL7+ (whichever fl-vers
    #      selected as the live one for that product).
    #   3. Highest BL7+ across all products (promotion case: symlink points at
    #      an older version but newer builds exist alongside).
    # Init prints a note when the current-symlink target had to be promoted
    # past a BL5/BL6 install. If no supported root exists, init refuses.
    running = detect_running_build()
    running_product = running.product if running else None
    per_product_current = {
        prod.name: str(prod.current_symlink) for prod in LAYOUT.products
    }
    supported = sorted(
        (r for r in baselight_roots if is_supported_version(r.get("version"))),
        key=lambda r: r.get("version") or "",
    )

    def _symlink_match(product: str) -> dict | None:
        target = per_product_current.get(product)
        if not target:
            return None
        m = next((r for r in baselight_roots
                  if r.get("path") == target
                  and (r.get("product") or "baselight") == product), None)
        if m and is_supported_version(m.get("version")):
            return m
        return None

    def _highest_supported(product: str) -> dict | None:
        matching = [r for r in supported if (r.get("product") or "baselight") == product]
        return matching[-1] if matching else None

    default_root = None
    # 0. The exact build serving flapid, if it's one of the configured roots
    #    (release or dev). Compared by real path so symlinked checkouts match.
    if running is not None:
        default_root = next((r for r in baselight_roots
                             if is_supported_version(r.get("version"))
                             and same_build(r["path"], running)), None)
    # 1. Running product's live symlink target (best case: fl-vers points at
    #    a v7+ of the product currently serving flapid).
    if default_root is None and running_product:
        default_root = _symlink_match(running_product)
    # 2. Running product's highest v7+ version — covers the case where the
    #    symlink hasn't been updated (e.g. fresh Daylight install still
    #    leaves the daylight symlink on an older Daylight version).
    if default_root is None and running_product:
        default_root = _highest_supported(running_product)
    # 3. Any product's live symlink target that's v7+.
    if default_root is None:
        for prod in LAYOUT.products:
            default_root = _symlink_match(prod.name)
            if default_root:
                break
    # 4. Highest v7+ across all products.
    if default_root is None and supported:
        default_root = supported[-1]
    # 5. Anything, so init can error out cleanly.
    if default_root is None and baselight_roots:
        default_root = baselight_roots[0]
    default_root_path = default_root["path"] if default_root else None

    # Resolve the managed venv authoritatively via `fl-setup-flapi-scripts -e`
    # (the same source app-script readiness uses). Only record it if it actually
    # exists — otherwise leave it null so init's "create the venv" guidance fires
    # (don't let a stale legacy venv mask a missing one).
    active_venv = None
    layout = None
    if default_root:
        layout = resolve_layout(Path(default_root_path), default_root.get("kind", "release"),
                                default_root.get("label"))
        venv = fl_setup_venv(layout.setup_scripts)
        if venv and (venv / "bin" / "python").exists():
            active_venv = str(venv)

    # Context sources: the canonical enhancements repo (git) first, then the
    # target build's bundled examples, then any extra dirs the user registered.
    sources: list[dict] = [{
        "type": "git",
        "path": str(REPO_DIR),
        "url": "https://github.com/FilmLightAPI/enhancements.git",
        "enabled": True,
    }]
    examples = layout.examples if layout else None
    if examples is None:
        examples = next((br.examples for br in disc.release_roots if br.examples), None)
    if examples is not None:
        sources.append({"type": "local", "path": str(examples), "enabled": True})
    for path in (extra_sources or []):
        sources.append({"type": "local", "path": path, "enabled": True})

    return {
        "platform": _platform_name(),
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
