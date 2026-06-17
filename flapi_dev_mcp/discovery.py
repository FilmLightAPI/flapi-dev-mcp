"""Local Baselight / FLAPI discovery (macOS + Linux, Python only — v1).

Two distinct trees (see CLAUDE.md):

  * Data root: the FilmLight runtime tree (venvs, scripts/, server-scripts/,
    blsiteprefs). `/Library/Application Support/FilmLight/` on macOS,
    `/usr/fl/` on Linux.

  * Build roots: an installed Baselight or a dev build/checkout. On macOS this
    is an `.app` bundle and every sub-path hangs off `<app>/Contents/`. On
    Linux the build root is a plain directory (e.g. `/usr/fl/baselight-X.Y.Z/`)
    and the sub-paths hang off the root directly. Both layouts are reached
    through `LAYOUT.resolve_base(root)`, which returns the dir holding
    `share/`, `bin/`, `doc/` for the OS at hand.

All functions degrade gracefully: missing pieces come back as None / empty,
never raise, so the MCP still works with a partial environment.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_VERSION_RE = re.compile(r"(\d+\.\d+)")


# --------------------------------------------------------------------------- #
# Platform layout
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PlatformLayout:
    data_root: Path
    apps_dir: Path                    # where installed versions live
    apps_child_glob: str              # glob under apps_dir for version dirs/roots
    python_dir: Path                  # parent of <pyver>...-venv dirs
    # Script-deploy dirs are listed as candidates in preference order. The
    # cross-platform convention `/vol/.support/{scripts,server-scripts}` is
    # tried first (typically a symlink to the OS-native dir); the OS-native
    # path is the fallback. discover_data_root picks the first that exists.
    ui_scripts_candidates: tuple[Path, ...]
    server_scripts_candidates: tuple[Path, ...]
    site_prefs_path: Path | None      # facility-wide prefs; may be absent
    user_prefs_path: Path | None      # per-user prefs; exists once Baselight launched
    prefs_keys: tuple[str, ...]       # search order inside the prefs files
    docs_html_rel: tuple[str, ...]    # candidate relative paths to rendered Python docs
    token_path: Path                  # FLAPI auth token
    current_symlink: Path             # stable "current build" symlink; may not exist
    resolve_base: Callable[[Path], "Path | None"]  # root -> dir with share/, bin/, doc/


def _resolve_base_mac(root: Path) -> Path | None:
    app = find_app_bundle(Path(root))
    return (app / "Contents") if app else None


def _resolve_base_linux(root: Path) -> Path | None:
    root = Path(root)
    return root if root.is_dir() else None


def _platform_layout() -> PlatformLayout:
    home = Path.home()
    # FilmLight's cross-platform convention. On BL hosts these are symlinks to
    # the OS-native dirs; on dev workstations they may be absent entirely.
    vol_ui = Path("/vol/.support/scripts")
    vol_server = Path("/vol/.support/server-scripts")
    if sys.platform == "darwin":
        data = Path("/Library/Application Support/FilmLight")
        return PlatformLayout(
            data_root=data,
            apps_dir=Path("/Applications/Baselight"),
            apps_child_glob="*",
            python_dir=data / "python",
            ui_scripts_candidates=(vol_ui, data / "scripts"),
            server_scripts_candidates=(vol_server, data / "server-scripts"),
            site_prefs_path=data / "Baselight" / "blsiteprefs",
            user_prefs_path=home / "Library" / "Preferences" / "FilmLight" / "Baselight" / "bluserprefs",
            prefs_keys=("flapi_python_path__Mac", "flapi_python_path"),
            docs_html_rel=("doc/flapi/python.html",),
            token_path=home / "Library" / "Preferences" / "FilmLight" / "flapi-token",
            current_symlink=Path("/Applications/Baselight/Current"),
            resolve_base=_resolve_base_mac,
        )
    if sys.platform.startswith("linux"):
        fl = Path("/usr/fl")
        return PlatformLayout(
            data_root=fl,
            apps_dir=fl,
            apps_child_glob="baselight-*",
            python_dir=fl / "python",
            ui_scripts_candidates=(vol_ui, fl / "scripts"),
            server_scripts_candidates=(vol_server, fl / "server-scripts"),
            site_prefs_path=None,  # facility-wide; not present on a fresh BL1
            user_prefs_path=home / ".baselight" / "bluserprefs",
            prefs_keys=("flapi_python_path__Linux", "flapi_python_path"),
            docs_html_rel=("doc/python.html", "doc/flapi/python.html"),
            token_path=home / ".filmlight" / "flapi-token",
            current_symlink=fl / "baselight",
            resolve_base=_resolve_base_linux,
        )
    raise RuntimeError(f"unsupported platform: {sys.platform}")


LAYOUT = _platform_layout()

# Back-compat aliases. Existing callers (config.py, app_scripts.py, …) import
# these directly; keep them stable so this diff stays surgical.
DATA_ROOT = LAYOUT.data_root
APPS_DIR = LAYOUT.apps_dir


# --------------------------------------------------------------------------- #
# Data root
# --------------------------------------------------------------------------- #

@dataclass
class DataRoot:
    root: Path
    exists: bool
    site_prefs: Path | None = None
    user_prefs: Path | None = None
    # `flapi_python_path` is the value of `flapi_python_path__<OS>` (or the
    # unqualified `flapi_python_path`) from bluserprefs / blsiteprefs. It is an
    # *override* — absent on a stock install, in which case the venv comes from
    # `fl-setup-flapi-scripts -e` and there is no problem to report.
    flapi_python_path: str | None = None
    python_minor: str | None = None
    python_dir: Path | None = None
    venvs: list[Path] = field(default_factory=list)
    ui_scripts_dir: Path | None = None                       # chosen path
    server_scripts_dir: Path | None = None                   # chosen path
    ui_scripts_candidates: list[Path] = field(default_factory=list)
    server_scripts_candidates: list[Path] = field(default_factory=list)


def parse_site_prefs(site_prefs: Path) -> str | None:
    """Return the FLAPI base interpreter path from a prefs file, or None.

    Works for both blsiteprefs (facility-wide) and bluserprefs (per-user) —
    the file format is identical. Keys probed are LAYOUT.prefs_keys, in order.
    """
    try:
        text = site_prefs.read_text(errors="replace")
    except OSError:
        return None
    for key in LAYOUT.prefs_keys:
        m = re.search(rf'^\s*{re.escape(key)}\s*=\s*"(.+?)"\s*;', text, re.MULTILINE)
        if m:
            return m.group(1)
    return None


def _python_minor(python_path: str | None) -> str | None:
    """Extract major.minor (e.g. '3.11') from an interpreter path."""
    if not python_path:
        return None
    # Prefer the framework '.../Versions/3.11/...' form, else any X.Y in the path.
    m = re.search(r"Versions/(\d+\.\d+)/", python_path) or _VERSION_RE.search(python_path)
    return m.group(1) if m else None


def baselight_major(version: str | None) -> str | None:
    """'7.0.1.25379' -> '7'."""
    if not version:
        return None
    m = re.match(r"(\d+)\.", version)
    return m.group(1) if m else None


# Minimum Baselight major version this MCP supports. The wheel-based FLAPI
# distribution (filmlightapi-*.whl + fl-setup-flapi-scripts) was introduced
# in BL7.0.0.24232. BL5/BL6 use a fundamentally different FLAPI delivery
# model and aren't supported. Set to 7 so v5/v6 installs are recognized but
# refused with a clear message.
MIN_SUPPORTED_MAJOR = 7


def is_supported_version(version: str | None) -> bool:
    """True if the given Baselight version is at our supported floor (BL7+)."""
    major = baselight_major(version)
    try:
        return int(major) >= MIN_SUPPORTED_MAJOR if major else False
    except ValueError:
        return False


def resolve_venv(python_dir: Path | None, python_minor: str | None, bl_major: str | None) -> Path | None:
    """Resolve the venv for a (python minor, Baselight major) pair.

    Venv naming has drifted across releases and differs by OS:

      macOS:  `3.12-v7-venv`                   (modern)
              `3.11.6-venv`                    (legacy, pre v<major>)
      Linux:  `3.12-rocky-8-v7-venv`           (modern, with distro infix)
              `3.9.16-rocky-8.8-venv`          (older, no v<major>)
              `3.6.12-centos-6.4-venv`         (different distro)

    Strategy: prefer modern names containing `-v<bl_major>-`; allow an
    arbitrary infix between `<python_minor>` and `-v<bl_major>-`. Fall back to
    a legacy `<python_minor>*-venv` without the v<major> marker. Both queries
    use a glob, so the resolver doesn't care about the distro tag, the OS, or
    whether full or short Python versions are encoded in the name.
    """
    if not python_dir or not python_minor:
        return None
    if bl_major:
        modern = [
            p for p in python_dir.glob(f"{python_minor}*-v{bl_major}-venv")
            if p.is_dir()
        ]
        if modern:
            return sorted(modern)[-1]  # lex-max → newest-looking name
    legacy = [
        p for p in python_dir.glob(f"{python_minor}*-venv")
        if p.is_dir() and not re.search(r"-v\d+-venv$", p.name)
    ]
    return sorted(legacy)[-1] if legacy else None


def fl_setup_venv(setup_scripts: Path | None) -> Path | None:
    """Ask Baselight's own `fl-setup-flapi-scripts -e` for the managed venv path.

    Authoritative — no prefs parsing or venv-name guessing, and it returns
    a sensible default (3.12) even with no interpreter pref set. Returns the
    path it names (which may not exist yet — caller checks). None if the tool
    is absent or errors.
    """
    if not setup_scripts or not Path(setup_scripts).exists():
        return None
    try:
        r = subprocess.run([str(setup_scripts), "-e"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    path = r.stdout.strip()
    return Path(path) if r.returncode == 0 and path else None


def discover_data_root() -> DataRoot:
    root = LAYOUT.data_root
    if not root.is_dir():
        return DataRoot(root=root, exists=False)

    site_prefs = LAYOUT.site_prefs_path if (LAYOUT.site_prefs_path and LAYOUT.site_prefs_path.is_file()) else None
    user_prefs = LAYOUT.user_prefs_path if (LAYOUT.user_prefs_path and LAYOUT.user_prefs_path.is_file()) else None

    # User pref takes precedence (per-user override), then site (facility-wide).
    flapi_python = None
    for p in (user_prefs, site_prefs):
        if p:
            flapi_python = parse_site_prefs(p)
            if flapi_python:
                break

    python_dir = LAYOUT.python_dir
    venvs = sorted(p for p in python_dir.glob("*-venv") if p.is_dir()) if python_dir.is_dir() else []

    ui = next((p for p in LAYOUT.ui_scripts_candidates if p.is_dir()), None)
    server = next((p for p in LAYOUT.server_scripts_candidates if p.is_dir()), None)

    return DataRoot(
        root=root,
        exists=True,
        site_prefs=site_prefs,
        user_prefs=user_prefs,
        flapi_python_path=flapi_python,
        python_minor=_python_minor(flapi_python),
        python_dir=python_dir if python_dir.is_dir() else None,
        venvs=venvs,
        ui_scripts_dir=ui,
        server_scripts_dir=server,
        ui_scripts_candidates=list(LAYOUT.ui_scripts_candidates),
        server_scripts_candidates=list(LAYOUT.server_scripts_candidates),
    )


# --------------------------------------------------------------------------- #
# Build roots
# --------------------------------------------------------------------------- #

@dataclass
class BuildRoot:
    path: Path                 # the root as configured
    kind: str                  # 'release' | 'dev-build' | 'dev-source'
    label: str | None = None
    app: Path | None = None    # resolved .app bundle (macOS only; None on Linux)
    version: str | None = None
    wheel: Path | None = None
    flapid: Path | None = None
    setup_scripts: Path | None = None   # fl-setup-flapi-scripts
    setup_token: Path | None = None     # fl-setup-flapi-token
    docs_html: Path | None = None       # doc/flapi/python.html or doc/python.html
    schema: Path | None = None          # share/flapi/schema/schema.json
    examples: Path | None = None        # share/flapi/examples/python
    offline_wheels: Path | None = None  # share/python (third-party dep wheels)

    @property
    def usable(self) -> bool:
        return self.wheel is not None and self.flapid is not None


def find_app_bundle(path: Path) -> Path | None:
    """Resolve a Baselight .app bundle from a configured root path (macOS).

    - root itself is an .app           -> use it
    - root contains Baselight-*.app    -> use that (e.g. /Applications/Baselight/<ver>/)
    - dev-source checkout              -> find the built .app under build/**

    Returns None on Linux — there are no .app bundles there; callers should
    use `LAYOUT.resolve_base(root)` instead.
    """
    path = Path(path)
    if path.suffix == ".app" and path.is_dir():
        return path
    if not path.exists():
        return None
    direct = sorted(path.glob("Baselight-*.app"))
    if direct:
        return direct[0]
    deep = sorted(path.glob("build/**/Baselight-*.app"))
    return deep[0] if deep else None


def resolve_layout(root_path: Path, kind: str, label: str | None = None) -> BuildRoot:
    """Resolve every sub-path the MCP needs from a build root."""
    br = BuildRoot(path=Path(root_path), kind=kind, label=label)
    base = LAYOUT.resolve_base(Path(root_path))
    if base is None:
        return br

    if sys.platform == "darwin":
        app = find_app_bundle(Path(root_path))
        br.app = app
        m = re.search(r"Baselight-(.+)\.app$", app.name) if app else None
        br.version = m.group(1) if m else None
    else:
        br.app = None
        # /usr/fl/baselight-7.0.1.25297 → 7.0.1.25297
        # /usr/fl/baselight (symlink → baselight-X.Y.Z) → X.Y.Z, by
        # resolving the symlink first; falls back to the literal name.
        try:
            real_name = Path(root_path).resolve().name
        except OSError:
            real_name = Path(root_path).name
        m = re.search(r"baselight-(.+)$", real_name) or re.search(r"baselight-(.+)$", Path(root_path).name)
        br.version = m.group(1) if m else None

    def first(parent: Path, pattern: str) -> Path | None:
        if not parent.is_dir():
            return None
        hits = sorted(parent.glob(pattern))
        return hits[0] if hits else None

    br.wheel = first(base / "share" / "flapi" / "python", "filmlightapi-*.whl")

    flapid = base / "bin" / "flapid"
    br.flapid = flapid if flapid.exists() else None

    fss = base / "bin" / "fl-setup-flapi-scripts"
    br.setup_scripts = fss if fss.exists() else None
    ftok = base / "bin" / "fl-setup-flapi-token"
    br.setup_token = ftok if ftok.exists() else None

    for rel in LAYOUT.docs_html_rel:
        cand = base / rel
        if cand.exists():
            br.docs_html = cand
            break

    schema = base / "share" / "flapi" / "schema" / "schema.json"
    br.schema = schema if schema.exists() else None

    examples = base / "share" / "flapi" / "examples" / "python"
    br.examples = examples if examples.is_dir() else None

    offline = base / "share" / "python"
    br.offline_wheels = offline if offline.is_dir() else None

    return br


def _process_exe(pid: str) -> Path | None:
    """Resolve a PID to its executable path. Works on macOS (ps) and Linux (/proc).

    On Linux, `/proc/<pid>/exe` is a symlink readable only by the process owner
    or root, so it fails for filmlight@... probing root-owned flapid. Fall back
    to `/proc/<pid>/cmdline` (world-readable), whose first NUL-separated field
    carries the absolute path the process was launched with.
    """
    if sys.platform.startswith("linux"):
        try:
            return Path(os.readlink(f"/proc/{pid}/exe"))
        except OSError:
            pass
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                first = f.read().split(b"\x00", 1)[0]
            return Path(first.decode("utf-8", "replace")) if first else None
        except OSError:
            return None
    try:
        # `command=` returns the full invocation; the first token is the path.
        out = subprocess.run(["ps", "-o", "command=", "-p", pid],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.split()[0]) if out else None


def _linux_flapid_pids() -> list[str]:
    """All running flapid PIDs (via pgrep), since `lsof -iTCP:1984` requires
    root to see other-owned listeners. flapid actually runs under fl-supervise
    -> flici -> flapid, so we look for any process whose cmdline includes the
    flapid binary path."""
    try:
        r = subprocess.run(["pgrep", "-f", "/bin/flapid"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    return [p for p in r.stdout.split() if p.isdigit()]


def detect_running_build() -> BuildRoot | None:
    """Resolve the Baselight build actually serving on :1984 (the live flapid/app).

    Finds the listening process, resolves its executable to the enclosing
    build root, and returns its layout. The build you're really talking to,
    which may differ from the configured target.
    """
    if sys.platform.startswith("linux"):
        pids = _linux_flapid_pids()
    else:
        try:
            r = subprocess.run(["lsof", "-nP", "-iTCP:1984", "-sTCP:LISTEN"],
                               capture_output=True, text=True, timeout=8)
        except (OSError, subprocess.SubprocessError):
            return None
        pids = []
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                pids.append(parts[1])
    for pid in dict.fromkeys(pids):
        exe = _process_exe(pid)
        if not exe:
            continue
        if sys.platform == "darwin":
            app = next((anc for anc in [exe, *exe.parents] if anc.suffix == ".app"), None)
            if app is None:
                continue
            kind = "release" if str(app).startswith(str(LAYOUT.apps_dir)) else "dev-build"
            return resolve_layout(app, kind=kind)
        # Linux: walk up until we hit a /usr/fl/baselight-* directory. The
        # cmdline path on this branch is something like
        # /usr/fl/baselight-6.0.25544/bin/flapid; its grandparent is the build.
        root = next(
            (anc for anc in [exe, *exe.parents]
             if anc.parent == LAYOUT.apps_dir and anc.name.startswith("baselight-")),
            None,
        )
        if root is None:
            continue
        return resolve_layout(root, kind="release")
    return None


def discover_release_roots() -> list[BuildRoot]:
    """Find installed release builds.

    macOS: subdirs of /Applications/Baselight/ (skipping the `Current` symlink).
    Linux: siblings under /usr/fl/ matching `baselight-*` (skipping the
    `baselight` symlink).
    """
    if not LAYOUT.apps_dir.is_dir():
        return []
    roots: list[BuildRoot] = []
    for child in sorted(LAYOUT.apps_dir.glob(LAYOUT.apps_child_glob)):
        if child.is_symlink():
            continue
        if child.name in ("Current", "baselight"):
            continue
        if not child.is_dir():
            continue
        br = resolve_layout(child, kind="release")
        if LAYOUT.resolve_base(child) is not None and br.wheel is not None:
            roots.append(br)
    return roots


# --------------------------------------------------------------------------- #
# Top-level
# --------------------------------------------------------------------------- #

@dataclass
class Discovery:
    data_root: DataRoot
    release_roots: list[BuildRoot]


def discover() -> Discovery:
    return Discovery(
        data_root=discover_data_root(),
        release_roots=discover_release_roots(),
    )
