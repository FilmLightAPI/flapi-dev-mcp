"""Local Baselight / FLAPI discovery (macOS, Python only — v1).

Two distinct trees (see CLAUDE.md):

  * Data root: /Library/Application Support/FilmLight/ — runtime data, the
    Baselight-created venvs, the scripts/ and server-scripts/ dirs, and
    blsiteprefs (which names the active FLAPI Python).

  * Build roots: an installed app or a dev build/checkout. A `release` install
    and a `dev-build` share the SAME `<app>/Contents/...` layout; `dev-source`
    is a checkout whose built `.app` lives under build/**. Everything the MCP
    needs (the filmlightapi wheel, flapid, fl-setup tools, docs, JSON schema,
    bundled examples, offline dep wheels) is resolved from the `.app` bundle.

All functions degrade gracefully: missing pieces come back as None / empty,
never raise, so the MCP still works with a partial environment.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

DATA_ROOT = Path("/Library/Application Support/FilmLight")
APPS_DIR = Path("/Applications/Baselight")

_SITE_PREFS_KEYS = ("flapi_python_path__Mac", "flapi_python_path")
_VERSION_RE = re.compile(r"(\d+\.\d+)")


# --------------------------------------------------------------------------- #
# Data root
# --------------------------------------------------------------------------- #

@dataclass
class DataRoot:
    root: Path
    exists: bool
    site_prefs: Path | None = None
    flapi_python_path: str | None = None   # base interpreter named by blsiteprefs
    python_minor: str | None = None        # e.g. '3.11', parsed from flapi_python_path
    python_dir: Path | None = None         # …/FilmLight/python
    venvs: list[Path] = field(default_factory=list)
    ui_scripts_dir: Path | None = None     # scripts/
    server_scripts_dir: Path | None = None # server-scripts/


def parse_site_prefs(site_prefs: Path) -> str | None:
    """Return the FLAPI base interpreter path from blsiteprefs, or None."""
    try:
        text = site_prefs.read_text(errors="replace")
    except OSError:
        return None
    for key in _SITE_PREFS_KEYS:
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


def resolve_venv(python_dir: Path | None, python_minor: str | None, bl_major: str | None) -> Path | None:
    """Resolve the venv for a (python minor, Baselight major) pair, deterministically.

    Baselight names venvs `<python-minor>-v<baselight-major>-venv` (e.g.
    `3.11-v7-venv`), so we construct the exact name rather than guessing. We
    only fall back to a legacy `<full-version>-venv` (no `-v<major>-` segment)
    when the exact venv doesn't exist (older builds predate the convention).
    """
    if not python_dir or not python_minor:
        return None
    if bl_major:
        exact = python_dir / f"{python_minor}-v{bl_major}-venv"
        if exact.is_dir():
            return exact
    # Legacy fallback: a `<python-minor>.*-venv` with no `-v<major>-` marker.
    legacy = [
        p for p in python_dir.glob(f"{python_minor}*-venv")
        if p.is_dir() and not re.search(r"-v\d+-venv$", p.name)
    ]
    return sorted(legacy)[0] if legacy else None


def fl_setup_venv(setup_scripts: Path | None) -> Path | None:
    """Ask Baselight's own `fl-setup-flapi-scripts -e` for the managed venv path.

    Authoritative — no blsiteprefs parsing or venv-name guessing, and it returns
    a sensible default (3.12) even with no interpreter pref set. Returns the path
    it names (which may not exist yet — caller checks). None if the tool is
    absent or errors.
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
    root = DATA_ROOT
    if not root.is_dir():
        return DataRoot(root=root, exists=False)

    site_prefs = root / "Baselight" / "blsiteprefs"
    site_prefs = site_prefs if site_prefs.is_file() else None
    flapi_python = parse_site_prefs(site_prefs) if site_prefs else None

    python_dir = root / "python"
    venvs = sorted(p for p in python_dir.glob("*-venv") if p.is_dir()) if python_dir.is_dir() else []

    ui = root / "scripts"
    server = root / "server-scripts"

    return DataRoot(
        root=root,
        exists=True,
        site_prefs=site_prefs,
        flapi_python_path=flapi_python,
        python_minor=_python_minor(flapi_python),
        python_dir=python_dir if python_dir.is_dir() else None,
        venvs=venvs,
        ui_scripts_dir=ui if ui.is_dir() else None,
        server_scripts_dir=server if server.is_dir() else None,
    )


# --------------------------------------------------------------------------- #
# Build roots
# --------------------------------------------------------------------------- #

@dataclass
class BuildRoot:
    path: Path                 # the root as configured (may be a symlink dir or an .app)
    kind: str                  # 'release' | 'dev-build' | 'dev-source'
    label: str | None = None
    app: Path | None = None    # resolved .app bundle
    version: str | None = None
    wheel: Path | None = None
    flapid: Path | None = None
    setup_scripts: Path | None = None   # fl-setup-flapi-scripts
    setup_token: Path | None = None     # fl-setup-flapi-token
    docs_html: Path | None = None       # doc/flapi/python.html
    schema: Path | None = None          # share/flapi/schema/schema.json
    examples: Path | None = None        # share/flapi/examples/python
    offline_wheels: Path | None = None  # share/python (third-party dep wheels)

    @property
    def usable(self) -> bool:
        return self.app is not None and self.wheel is not None


def find_app_bundle(path: Path) -> Path | None:
    """Resolve a Baselight .app bundle from a configured root path.

    - root itself is an .app           -> use it
    - root contains Baselight-*.app    -> use that (e.g. /Applications/Baselight/<ver>/)
    - root is a symlink dir (Current)  -> resolved above after globbing
    - dev-source checkout              -> find the built .app under build/**
    """
    path = Path(path)
    if path.suffix == ".app" and path.is_dir():
        return path
    if not path.exists():
        return None
    # Direct child .app (release version dir, or a dir holding the bundle).
    direct = sorted(path.glob("Baselight-*.app"))
    if direct:
        return direct[0]
    # Dev-source checkout: built bundle somewhere under build/**.
    deep = sorted(path.glob("build/**/Baselight-*.app"))
    return deep[0] if deep else None


def resolve_layout(root_path: Path, kind: str, label: str | None = None) -> BuildRoot:
    """Resolve every sub-path the MCP needs from a build root."""
    br = BuildRoot(path=Path(root_path), kind=kind, label=label)
    app = find_app_bundle(Path(root_path))
    if app is None:
        return br
    br.app = app

    m = re.search(r"Baselight-(.+)\.app$", app.name)
    br.version = m.group(1) if m else None

    contents = app / "Contents"

    def first(glob_parent: Path, pattern: str) -> Path | None:
        if not glob_parent.is_dir():
            return None
        hits = sorted(glob_parent.glob(pattern))
        return hits[0] if hits else None

    br.wheel = first(contents / "share" / "flapi" / "python", "filmlightapi-*.whl")

    flapid = contents / "bin" / "flapid"
    br.flapid = flapid if flapid.exists() else None

    fss = contents / "bin" / "fl-setup-flapi-scripts"
    br.setup_scripts = fss if fss.exists() else None
    ftok = contents / "bin" / "fl-setup-flapi-token"
    br.setup_token = ftok if ftok.exists() else None

    docs = contents / "doc" / "flapi" / "python.html"
    br.docs_html = docs if docs.exists() else None

    schema = contents / "share" / "flapi" / "schema" / "schema.json"
    br.schema = schema if schema.exists() else None

    examples = contents / "share" / "flapi" / "examples" / "python"
    br.examples = examples if examples.is_dir() else None

    offline = contents / "share" / "python"
    br.offline_wheels = offline if offline.is_dir() else None

    return br


def detect_running_build() -> BuildRoot | None:
    """Resolve the Baselight build actually serving on :1984 (the live flapid/app).

    Finds the listening process, resolves its executable to the enclosing
    `.app`, and returns its layout. This is the build you're really talking to,
    which may differ from the configured target (see mismatch check).
    """
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
        try:
            exe = subprocess.run(["ps", "-o", "comm=", "-p", pid],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        app = next((anc for anc in [Path(exe), *Path(exe).parents] if anc.suffix == ".app"), None)
        if app is None:
            continue
        kind = "release" if str(app).startswith(str(APPS_DIR)) else "dev-build"
        return resolve_layout(app, kind=kind)
    return None


def discover_release_roots() -> list[BuildRoot]:
    """Find installed release builds under /Applications/Baselight/<ver>/.

    Skips the `Current` symlink to avoid a duplicate; reports concrete versions.
    """
    if not APPS_DIR.is_dir():
        return []
    roots: list[BuildRoot] = []
    for child in sorted(APPS_DIR.iterdir()):
        if child.name == "Current" or child.is_symlink():
            continue
        if not child.is_dir():
            continue
        br = resolve_layout(child, kind="release")
        if br.app is not None:
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
