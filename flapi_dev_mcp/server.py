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
    filenames and file contents. Call this early when writing a script to find
    similar existing ones to learn from or adapt. Returns matching files with
    the source they came from and a few matching-line snippets, ranked by
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
