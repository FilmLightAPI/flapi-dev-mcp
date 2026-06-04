"""The MCP server.

Step 1 scaffold: starts over stdio and registers a single dummy tool so we can
verify Claude Code connects and sees the tool. Real tools (environment, context,
script) are added in later steps.
"""

from __future__ import annotations

import platform
import sys

from mcp.server.fastmcp import FastMCP

from flapi_dev_mcp import __version__
from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc

mcp = FastMCP("flapi-dev")


@mcp.tool()
def flapi_dev_ping() -> str:
    """Connectivity check for the FLAPI Developer MCP.

    Call this to confirm the flapi-dev MCP server is running and reachable.
    Returns the server version and host platform. This is a scaffold tool;
    the environment, context, and script tools are added in later build steps.
    """
    return (
        f"flapi-dev-mcp {__version__} is alive — "
        f"python {platform.python_version()} on {platform.system()} {platform.machine()}"
    )


@mcp.tool()
def flapi_check_environment() -> dict:
    """Report the discovered FLAPI environment on this machine (macOS, Python only).

    Call this early when writing any FLAPI script — it tells you what Baselight is
    installed, which venv FLAPI uses, and where the script directories live. Runs
    live discovery (not just cached config). Returns the data root (active venv,
    FLAPI Python, scripts/ and server-scripts/ dirs) and every release build root
    with its resolved wheel / flapid / docs / schema / examples paths.
    """
    d = disc.discover()
    dr = d.data_root
    default = d.release_roots[0] if d.release_roots else None
    major = disc.baselight_major(default.version) if default else None
    active_venv = disc.resolve_venv(dr.python_dir, dr.python_minor, major)
    return {
        "platform": "macos",
        "data_root": {
            "exists": dr.exists,
            "flapi_python_path": dr.flapi_python_path,
            "python_minor": dr.python_minor,
            "venvs": [v.name for v in dr.venvs],
            "active_venv": str(active_venv) if active_venv else None,
            "ui_scripts_dir": str(dr.ui_scripts_dir) if dr.ui_scripts_dir else None,
            "server_scripts_dir": str(dr.server_scripts_dir) if dr.server_scripts_dir else None,
        },
        "release_roots": [_root_summary(br) for br in d.release_roots],
        "config_written": cfgmod.CONFIG_PATH.exists(),
    }


@mcp.tool()
def flapi_list_baselight_versions() -> list[dict]:
    """List installed Baselight build roots and the FLAPI assets resolved from each.

    Use this to choose which Baselight version to target. Returns, per root: the
    version, kind, the .app bundle, and resolved paths for the filmlightapi wheel,
    flapid, docs, JSON schema, and bundled examples.
    """
    return [_root_summary(br) for br in disc.discover().release_roots]


@mcp.tool()
def flapi_status() -> dict:
    """Report the saved FLAPI config (the same data as the `status` CLI command).

    Use this to show the user their resolved setup in-chat: target Baselight
    version, selected venv (and whether it's derived or overridden), docs / schema
    / example paths, script directories, build roots, and context sources. If it
    reports config_found=false, the user needs to run `flapi-dev-mcp init` first.
    """
    from flapi_dev_mcp import report
    return report.gather_status()


@mcp.tool()
def get_api_surface() -> dict:
    """Summarize the whole FLAPI surface from the build's JSON schema.

    Returns every class with its method names and signals, plus the names of all
    ValueTypes (settings structs) and Constants (enums). Call this to understand
    what's possible before drilling into a class with get_class_docs.
    """
    from flapi_dev_mcp import schema
    return schema.api_surface()


@mcp.tool()
def search_examples(query: str, limit: int = 10) -> dict:
    """Keyword-search example scripts across all context sources.

    Searches the cloned enhancements repo (App Scripts, FLAPI Tools, Shaders),
    the build's bundled examples, and any extra dirs the user registered, over
    filenames and file contents. **Call this BEFORE writing any FLAPI script**
    (and before reaching for external tools like ffmpeg) — there is very likely
    an idiomatic example (e.g. exporting stills, rendering, metadata) that's
    better to adapt than to reinvent. Then read the top hit in full. Returns
    matching files with their source and matching-line snippets, ranked by
    relevance. Searches: file/dir names, comments, function names, class usage.
    """
    from flapi_dev_mcp import search
    return search.search_examples(query, limit=limit)


@mcp.tool()
def get_class_docs(class_name: str) -> dict:
    """Full docs for one FLAPI class, from the build's JSON schema (ground truth).

    Returns each method with typed args, return type, and description, the class's
    signals, and a ready-to-read `markdown` rendering. Call this when writing code
    that uses a class (e.g. Scene, Application, ThumbnailManager) so signatures
    match the targeted build exactly. If not found, suggests similar class names.
    """
    from flapi_dev_mcp import schema
    return schema.class_docs(class_name)


@mcp.tool()
def check_app_script_readiness(kind: str = "both") -> dict:
    """Are we ready to deploy an App Script (one that runs inside Baselight)?

    kind: 'ui' (menu items/dialogs → scripts/), 'server' (background →
    server-scripts/), or 'both'. Checks Baselight's managed venv (`import flapi`)
    and that the deploy directory exists and is writable. Returns the deploy
    dir(s) to write the script into and the managed-venv interpreter, plus a
    step-by-step `workflow`. Call this when writing an App Script (vs a
    standalone script). BEFORE writing code, also call search_examples for a
    similar App Script (the repo's App Scripts have the menu/dialog boilerplate).
    """
    from flapi_dev_mcp import app_scripts
    return app_scripts.check_app_script_readiness(kind)


@mcp.tool()
def create_app_venv() -> dict:
    """Create/update Baselight's managed app-script venv (no sudo).

    Runs `fl-setup-flapi-scripts --create`, which builds the venv and installs the
    build-matching `filmlightapi` wheel. Call this when check_app_script_readiness
    reports the managed venv is missing (offer it to the user first; it can take a
    minute and downloads the wheel). Returns the resulting venv path and a log tail.
    """
    from flapi_dev_mcp import app_scripts
    return app_scripts.create_managed_venv()


@mcp.tool()
def install_app_dependencies(packages: list[str]) -> dict:
    """Pip-install packages into Baselight's MANAGED venv (where App Scripts run).

    Use for deps an App Script imports beyond flapi (e.g. Pillow). This is the
    App-Script counterpart of install_dependencies (which targets the separate
    standalone venv). Returns install status and a tail of the pip log.
    """
    from flapi_dev_mcp import app_scripts
    return app_scripts.install_app_dependencies(packages)


@mcp.tool()
def check_flapid(hostname: str = "", project_dir: str = "") -> dict:
    """Check whether a Baselight FLAPI daemon (flapid) is reachable.

    Opens a real FLAPI connection from the standalone venv (default host from
    config, usually localhost) and lists jobs. Pass project_dir (the folder
    where the script lives) so it uses that project's venv. Call this before
    running a standalone script. If it fails, help the user start Baselight or
    use the launch() pattern. Returns connection status, host, and jobs.
    """
    from flapi_dev_mcp import flapi_conn
    return flapi_conn.check_flapid(hostname or None, project_dir)


@mcp.tool()
def check_standalone_readiness(hostname: str = "", project_dir: str = "") -> dict:
    """Are we ready to run a standalone FLAPI script? Aggregates the checks.

    ALWAYS pass project_dir = your current working directory (the folder the
    script will live in). The standalone venv is then created there as
    `<project_dir>/.venv`, self-contained per project. (Omitting project_dir
    uses a shared home venv — avoid that.) Verifies the venv + `import flapi`,
    probes flapid connectivity, checks auth. Returns ready (bool) + per-part
    status and remedies.

    Call this at the START of a standalone script task. Then, BEFORE writing
    code, call search_examples to find a similar existing script to adapt — the
    repo has idiomatic FLAPI patterns (e.g. exporting stills) that are better
    than reinventing them.
    """
    from flapi_dev_mcp import flapi_conn
    return flapi_conn.check_standalone_readiness(hostname or None, project_dir)


@mcp.tool()
def setup_standalone_env(project_dir: str = "", reinstall_wheel: bool = False) -> dict:
    """Create/verify the per-project venv for standalone FLAPI scripts.

    ALWAYS pass project_dir = your current working directory; the venv is created
    there as `<project_dir>/.venv` — self-contained and isolated per project,
    built from Baselight's base Python with the build-matching `filmlightapi`
    wheel, `import flapi` confirmed. (Omitting project_dir falls back to a shared
    ~/.flapi-dev-mcp/venvs/<version>/ — avoid unless there is genuinely no
    project folder.) Never touches Baselight's app-script venvs.
    """
    from flapi_dev_mcp import venvs
    return venvs.setup_standalone_env(project_dir, reinstall_wheel=reinstall_wheel)


@mcp.tool()
def install_dependencies(packages: list[str], project_dir: str = "") -> dict:
    """Pip-install third-party packages into the standalone venv (e.g. Pillow).

    ALWAYS pass project_dir = your current working directory so deps install into
    that project's `<project_dir>/.venv` (the same venv setup_standalone_env /
    check_standalone_readiness use). Sets the venv up first if needed. For deps a
    standalone script imports beyond `flapi`. Never touches app-script venvs.
    """
    from flapi_dev_mcp import venvs
    return venvs.install_dependencies(packages, project_dir)


@mcp.tool()
def reload_app_scripts(host: str = "localhost", port: int = 1984) -> dict:
    """Reload Baselight's app scripts programmatically (the "Reload Scripts" button).

    After writing/editing an App Script, call this to make Baselight pick it up
    (HTTP GET :<port>/reload-scripts → restarts the server's Python). IMPORTANT:
    UI scripts and server scripts are served by different servers. The UI/app
    server uses the flapi_port_number pref (normally 1984); if a UI script
    doesn't reload, you're likely hitting flapid (server scripts) — pass the app
    server's real port. After reloading, read get_flapi_log for load errors; for
    a UI menu item the user still clicks it. Fallback: `sudo fl-service restart flapi`.
    """
    from flapi_dev_mcp import app_scripts
    return app_scripts.reload_app_scripts(host, port)


@mcp.tool()
def get_app_script_log(lines: int = 80) -> dict:
    """Tail the live APP/UI-script log — `$FLTMPDIR/plugins.log`.

    This is the file the GUI's Views > Scripts > (gear) > Open Log File shows.
    It captures app-script print output AND load/import tracebacks. Resolves the
    path from the running Baselight GUI. Call after reloading a UI script (and
    after the user clicks the menu item) to see what happened. For SERVER scripts
    use get_flapi_log instead.
    """
    from flapi_dev_mcp import app_scripts
    return app_scripts.get_app_script_log(lines)


@mcp.tool()
def get_flapi_log(lines: int = 80) -> dict:
    """Tail the live flapid console log — SERVER-script output and flapid errors.

    Reliably finds the current `<host>-flapid` log under /vol/.support/log. Use
    after reloading a server script to see its output and any load tracebacks.
    NOTE: this is flapid only (server scripts). UI/app-script output is NOT here —
    for those, read the script's own self-log file (the readiness workflow makes
    app scripts redirect stdout/stderr to ~/.flapi-dev-mcp/logs/<name>.log).
    """
    from flapi_dev_mcp import app_scripts
    return app_scripts.get_flapi_log(lines)


def _root_summary(br: disc.BuildRoot) -> dict:
    return {
        "version": br.version,
        "kind": br.kind,
        "app": str(br.app) if br.app else None,
        "usable": br.usable,
        "wheel": str(br.wheel) if br.wheel else None,
        "flapid": str(br.flapid) if br.flapid else None,
        "docs_html": str(br.docs_html) if br.docs_html else None,
        "schema": str(br.schema) if br.schema else None,
        "examples": str(br.examples) if br.examples else None,
    }


def run() -> None:
    """Start the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    sys.exit(run())
