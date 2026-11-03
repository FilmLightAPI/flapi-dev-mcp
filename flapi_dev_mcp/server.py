"""The MCP server: the tools a coding agent calls to write FLAPI scripts.

Tools fall into four groups: setup info (flapi_status), FLAPI knowledge
(get_api_surface, get_class_docs, search_examples), standalone scripts
(readiness, connection, venv, deps) and App Scripts (readiness, venv, deps,
reload, logs). Logic lives in the other modules; these are thin wrappers whose
docstrings are what the agent reads when choosing a tool.
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from flapi_dev_mcp import config as cfgmod
from flapi_dev_mcp import discovery as disc
from flapi_dev_mcp.instructions import INSTRUCTIONS

mcp = FastMCP("flapi-dev", instructions=INSTRUCTIONS)


@mcp.tool()
def flapi_status() -> dict:
    """The user's FLAPI setup: target build, venvs, script folders, installed builds.

    Call this when the user asks what's installed or how they're set up, or when
    another tool reports a setup problem. Returns the target Baselight/Daylight
    build and version, the build serving flapid right now, the App Script venv,
    the scripts/ and server-scripts/ folders, every installed build with its
    wheel, docs, schema and examples, and the context sources. If
    config_found is false, the user needs to run `flapi-dev-mcp init` first.
    Not needed before writing a script: the readiness tools cover that.
    """
    from flapi_dev_mcp import report
    status = report.gather_status()
    running = disc.detect_running_build()
    status["running_build"] = _root_summary(running) if running else None
    status["installed_builds"] = [_root_summary(br) for br in disc.discover().release_roots]
    return status


@mcp.tool()
def get_api_surface() -> dict:
    """Summarize the whole FLAPI surface from the build's JSON schema.

    Returns every class with its method names and signals, plus the names of all
    ValueTypes (settings structs) and Constants (enums), for the build the user
    has. Call this to see what's possible before drilling into a class with
    get_class_docs. FLAPI changes between builds: trust this list over what you
    remember. If a class or method isn't here, it doesn't exist in this build.
    """
    from flapi_dev_mcp import schema
    return schema.api_surface()


@mcp.tool()
def search_examples(query: str, limit: int = 10) -> dict:
    """Keyword-search example scripts across all context sources.

    Searches the cloned enhancements repo (App Scripts, FLAPI Tools, Shaders),
    the build's bundled examples, and any extra dirs the user registered, over
    filenames and file contents. **Call this BEFORE writing any FLAPI script**,
    and before reaching for outside tools like ffmpeg: there is very likely an
    idiomatic example (exporting stills, rendering, metadata, menu items) that's
    better to adapt than to reinvent. Then read the top hit in full. Use a few
    plain keywords for the task, e.g. "export still", "menu item scene",
    "render queue", rather than a sentence. Returns matching files with their
    source and matching-line snippets, ranked by relevance.
    """
    from flapi_dev_mcp import search
    return search.search_examples(query, limit=limit)


@mcp.tool()
def get_class_docs(class_name: str) -> dict:
    """Full docs for one FLAPI class, from the build's JSON schema (ground truth).

    Returns each method with typed args, return type, and description, the class's
    signals, and a ready-to-read `markdown` rendering. Call this for every class
    your code uses (e.g. Scene, Application, QueueManager) so signatures match the
    user's build exactly. A method that isn't listed doesn't exist in this build:
    don't invent one, tell the user instead. If the class isn't found, suggests
    similar names.
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
def flapi_connection(choice: str = "", host: str = "", port: int = 0,
                     username: str = "", project_dir: str = "") -> dict:
    """Pick & verify how a STANDALONE script connects to FLAPI. The connection target
    is a real fork — decide it before writing connect code.

    Two-step use (an MCP tool can't ask the user, so YOU do the asking):
    1. Call with NO choice → returns a menu of connection types with LIVE status:
       - 'flapid'  : headless daemon :1984. Opens scenes by name; app need not run.
                     Application is available, but there is no current scene
                     (get_current_scene() returns None). Local auto-auth;
                     remote needs a token.
       - 'app'     : the live running app :1985. Gives the current OPEN scene and
                     cursor/viewing state. Needs Baselight/Daylight running with a
                     scene open. Idiom: app = conn.Application.get() (an instance,
                     never flapi.Application.<method>()).
       - 'launch'  : spawn a private flapid from the build — fully headless.
       - 'remote'  : another machine's flapid/app; pass host(+port), needs a token.
       Present these to the user and ASK which fits the task (live/open scene & cursor
       & thumbnails → app; headless batch/render/export by name → flapid/launch).
    2. Call again with choice= (+ host/port/username) → it TESTS that connection and
       returns a ready-to-paste, verified `snippet` (connect + close) plus auth notes.

    Use this for the connection decision; use check_standalone_readiness for the venv/
    deps/import-flapi readiness. Pass project_dir = your cwd so it uses that venv.
    """
    from flapi_dev_mcp import flapi_conn
    return flapi_conn.connection_selector(choice, host, port, username, project_dir)


@mcp.tool()
def check_standalone_readiness(hostname: str = "", project_dir: str = "") -> dict:
    """Are we ready to run a standalone FLAPI script? Aggregates the checks.

    ALWAYS pass project_dir = your current working directory (the folder the
    script will live in). The standalone venv is then created there as
    `<project_dir>/.venv`, self-contained per project. (Omitting project_dir
    uses a shared home venv — avoid that.) Verifies the venv + `import flapi`,
    probes flapid connectivity, checks auth. Returns ready (bool) + per-part
    status and remedies.

    This is the HEADLESS path (connect to flapid :1984, open scenes by name; the
    app need not be running). If the script instead needs the LIVE open session —
    the currently-open scene, current cursor/viewing state, live thumbnails, or the
    Application class — use flapi_connection to pick the ':1985' live-app target
    instead. When unsure which the task wants, ASK the user.

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
    NOT for App Scripts: use install_app_dependencies for those.
    """
    from flapi_dev_mcp import venvs
    return venvs.install_dependencies(packages, project_dir)


@mcp.tool()
def reload_app_scripts(kind: str = "ui", host: str = "localhost", port: int = 0) -> dict:
    """Reload Baselight/Daylight app scripts (the "Reload Scripts" button) and confirm it worked.

    kind='ui' for UI scripts (asks the running app, :1985), kind='server' for
    server scripts (asks flapid, :1984). After writing or editing an App Script,
    call this, then read get_app_script_log (UI) or get_flapi_log (server) for
    load errors. If it returns restarted=false, the build ignored the request:
    ask the user to reload via Views > Scripts > (gear) > Reload Scripts.
    """
    from flapi_dev_mcp import app_scripts
    return app_scripts.reload_app_scripts(kind, host, port)


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

    Finds the current `<host>-flapid` log under /vol/.support/log. Use after
    reloading a server script to see its output and any load tracebacks, or when
    a standalone script gets an error back from flapid. For UI/App Script output
    use get_app_script_log instead.
    """
    from flapi_dev_mcp import app_scripts
    return app_scripts.get_flapi_log(lines)


def _root_summary(br: disc.BuildRoot) -> dict:
    return {
        "product": br.product,
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
