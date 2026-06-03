# FLAPI Developer MCP — Claude Code Project Spec

## Overview

A local MCP server for Claude Code that makes Claude an expert FLAPI developer. It dynamically gathers context from the local Baselight installation and the FLAPI GitHub repo (cloned on init), probes the live environment, scaffolds new scripts with the right boilerplate, and can run generated scripts to verify they work.

Ships as its own repo in the FilmLight GitHub org alongside Peter Postma's FLAPI repo. Two sibling repos in the same org. Developer clones it, runs init (which clones the sibling FLAPI repo for context), and configures Claude Code to use it.

## Architecture

- Local Python MCP server communicating via stdio
- Runs on the developer's machine alongside Baselight
- On init, clones the sibling FLAPI repo (github.com/FilmLight/flapi) to ~/.flapi-dev-mcp/repo/ for context
- On subsequent runs, git pulls to stay current with new examples and docs
- Discovers context dynamically from the local Baselight installation
- Carries its own patterns, gotchas, and templates that are tool-specific
- No vectorization — structured file lookup and keyword search over a small, well-organized corpus
- No cloud. No accounts. No infrastructure.

## Installation

FilmLight GitHub org layout:

```
github.com/FilmLight/flapi              # Peter's repo (docs, examples, API reference)
github.com/FilmLight/flapi-dev-mcp      # This repo (the MCP server)
```

Setup:

```bash
git clone https://github.com/FilmLight/flapi-dev-mcp
cd flapi-dev-mcp
python -m flapi_dev_mcp init
```

The `init` step is a **guided onboarding flow** built from rich sequential prompts (colored output, confirm-detected-paths, y/n toggles, validated path entry). No full TUI: init runs rarely, so the complexity budget stays small. It auto-discovers everything it can and only prompts for what it couldn't find, plus optional extras. The flow:

1. Creates ~/.flapi-dev-mcp/
2. Clones the sibling repo (github.com/FilmLight/flapi) into ~/.flapi-dev-mcp/repo/ as the first context source
3. Discovers the **data root** (`/Library/Application Support/FilmLight/`, macOS, Python only for v1): the active venv (via `blsiteprefs`), the `scripts/` and `server-scripts/` directories; and **release build roots** by scanning `/Applications/Baselight/*`. Confirms each detected path with the user
4. Prompts for any **dev build roots** to register (since a FilmLight dev box has no `/Applications/Baselight`; e.g. a `dev-build` `.app` bundle or a `dev-source` checkout), in an "add another?" loop
5. Prompts for anything discovery missed, the default build root, and the default flapid hostname (Camp A); notes auth (`flapi-token`) status and points to `fl-setup-flapi-token` if a remote target will be used
6. Prompts for any **extra context source directories** (studio script collections, other FLAPI-rich folders), in an "add another? (blank to finish)" loop
7. Writes config.json with the `sources` and `baselight_roots` lists, discovered paths, and default hostname

Re-running init is **idempotent**: it detects an existing config and offers to update individual values rather than blindly overwriting. Sources can also be managed after init without re-running the whole flow, via `config` subcommands:

```bash
python -m flapi_dev_mcp config list                 # show sources, baselight roots, host, discovered paths
python -m flapi_dev_mcp config add-source <path>    # register an extra local source dir
python -m flapi_dev_mcp config add-baselight-root <path> --kind dev-build|dev-source
python -m flapi_dev_mcp config remove-source <path>
python -m flapi_dev_mcp config enable-source <path> # toggle a source on/off
python -m flapi_dev_mcp config set-host <hostname>
```

Claude Code config (`.claude/mcp.json`):

```json
{
  "mcpServers": {
    "flapi-dev": {
      "command": "python",
      "args": ["-m", "flapi_dev_mcp"]
    }
  }
}
```

## Directory Layout

The MCP's own repo:

```
flapi-dev-mcp/
  pyproject.toml
  README.md
  flapi_dev_mcp/
    __main__.py          # Entry point, starts MCP server via stdio
    cli.py               # CLI commands (init, update, config)
    server.py            # MCP server implementation
    discovery.py         # Local Baselight installation discovery
    repo.py              # FLAPI repo cloning, pulling, indexing
    tools/
      environment.py     # check_baselight, check_flapid, check_python, list_jobs, validate_scene
      context.py         # get_class_docs, get_pattern, search_examples, search_gotchas, get_api_surface
      scripts.py         # create_script, run_script, test_script
    patterns/            # Boilerplate templates per script type (tool-specific, lives here)
    gotchas/             # Known pitfalls with solutions (tool-specific, lives here)
```

Created on init at ~/.flapi-dev-mcp/:

```
~/.flapi-dev-mcp/
  repo/              # Cloned FLAPI GitHub repo (examples, docs, API reference) — the first context source
  config.json        # Baselight hostname, discovered paths, generalized sources list, preferences
```

### config.json shape

Context sources are stored as a single uniform list. The cloned FLAPI repo is just source #0; user-registered directories are more entries. Every tool that searches for examples or docs iterates this one array, treating all sources identically. No special-casing of the clone.

```json
{
  "platform": "macos",
  "language": "python",
  "data_root": "/Library/Application Support/FilmLight",
  "flapid_host": "localhost",
  "baselight": {
    "ui_scripts_dir": "/Library/Application Support/FilmLight/scripts",
    "server_scripts_dir": "/Library/Application Support/FilmLight/server-scripts",
    "site_prefs": "/Library/Application Support/FilmLight/Baselight/blsiteprefs"
  },
  "baselight_roots": [
    { "kind": "release", "path": "/Applications/Baselight/Current", "enabled": true },
    {
      "kind": "dev-build",
      "path": "/Users/jason/branch-dev-slatedetection-25/build/baselight/DarwinArm-clang-1500/debug/Baselight-7.0.unknown.app",
      "label": "slatedetection",
      "enabled": true
    },
    {
      "kind": "dev-source",
      "path": "/Users/jason/Development/checkouts/branch-baselight-7-0-1-nab-2026",
      "label": "7.0.1-nab",
      "enabled": true,
      "overrides": { "flapi_python": null, "wheel": null, "flapid": null, "docs": null }
    }
  ],
  "default_root": "release",
  "sources": [
    { "type": "git", "path": "~/.flapi-dev-mcp/repo", "url": "https://github.com/FilmLight/flapi", "enabled": true },
    { "type": "local", "path": "/studio/flapi-scripts", "enabled": true }
  ]
}
```

**`language`: `python` only for v1.** The docs tree ships nodejs/java/javascript/json variants; the MCP ignores them and uses only the `python/` and `common/` docs.

**`data_root`** (`/Library/Application Support/FilmLight`) is the runtime data + auto-created venvs + `scripts/`/`server-scripts/` + `blsiteprefs`. It is distinct from a **build root** (the installed app or a dev build/checkout) which holds the flapi module, wheel, flapid binary, and docs.

**`baselight_roots`** is a generalized list mirroring `sources` (same enable/disable model). Each entry's `kind` selects a layout template for resolving sub-paths; `overrides` lets a nonstandard build pin any sub-path explicitly:

**All paths below are verified against a real `7.0.1` release install and a dev `7.0.1` checkout.** Crucial finding: a `release` install and a `dev-build` have the **identical `.app/Contents/` layout**, the FLAPI docs' `Utilities/Resources/share` / `Utilities/Tools` paths do not exist on macOS. So `release` and `dev-build` share one layout template (the `app-bundle` resolver) and differ only in how they are discovered. The resolver locates the `.app` from a root: the root itself if it ends in `.app`; else a `Baselight-*.app` within it (release root `/Applications/Baselight/Current` is a symlink to `…/<ver>/Baselight-<ver>.app`); for `dev-source` the `.app` is under `build/**/`.

| Need | `app-bundle` (`release` + `dev-build`), relative to `<app>/Contents/` | `dev-source` (checkout) extras |
|---|---|---|
| `filmlightapi` wheel | `share/flapi/python/filmlightapi-<ver>-py3-none-any.whl` | also in the built `.app` under `build/**/` |
| `flapid` binary | `bin/flapid` | the built `.app`'s `bin/flapid` |
| `fl-setup-flapi-scripts` / `fl-setup-flapi-token` | `bin/` | the built `.app`'s `bin/` |
| docs (Python) | `doc/flapi/python.html` (rendered) | `flapi/docs/{common,python}/*.md` + generated `build/**/gen/doc/flapi/python.md` |
| JSON schema | `share/flapi/schema/schema.json` | same, in the built `.app` |
| bundled examples | `share/flapi/examples/python/` (+ `install.sh`) | repo examples in the checkout |
| offline dep wheels | `share/python/*.whl` (third-party deps for offline `pip install`) | same |
| editable-install target | n/a (bundle ships only the wheel) | `build/**/gen/flapi/python` |

The `flapi` package is pure-Python: one module per API class (`Application.py`, `Scene.py`, …), a thin client that talks to flapid over a socket. It is distributed as the `filmlightapi` wheel and **installed into a venv** for every root kind, see below.

> The bundled `share/flapi/examples/python/` and `share/flapi/schema/schema.json` are first-class context: index the examples as a source, and use the schema for `get_api_surface` / validation. The bundled `share/python/*.whl` are exactly what `fl-setup-flapi-scripts` uses for offline dependency installs.

`release` roots are autodiscovered by scanning `/Applications/Baselight/*`; `dev-*` roots are user-added (init prompt or `config add-baselight-root <path> --kind dev-build|dev-source`). The active venv for Camp B is resolved live from `site_prefs` (`flapi_python_path__Mac`), never hardcoded. Each `sources` entry: `type` (`git`/`local`), `path`, optional `url`, `enabled`; on startup the server git-pulls enabled `git` sources and indexes all enabled sources.

### How flapi is installed for standalone (Camp A) scripts

A standalone script runs under an external Python that must be able to `import flapi`. There is **one mechanism for all root kinds: install the `filmlightapi` wheel into a venv.** (No PYTHONPATH-into-the-build trick: bundles ship only the wheel, and carrying a separate runtime-path code path isn't worth the brittleness.)

- Use a venv with a compatible Python (3.9+, default 3.12). Reuse the Baselight-created venv, or create/update one with `fl-setup-flapi-scripts --create`.
- `‹venv›/bin/pip install ‹root›/…/share/flapi/python/filmlightapi-‹ver›-py3-none-any.whl` (path per the layout table; resolved by `get_flapi_wheel`).
- Run the script with that venv's interpreter: `import flapi` resolves, alongside any third-party deps installed in the same venv (`install_dependencies`).
- Offline: `fl-setup-flapi-scripts --collect /tmp/packages` gathers the wheels; copy them over and `pip install /tmp/packages/*.whl`.

**Optional, only when actively hacking on flapi itself** (a `dev-source` root): `pip install -e ‹checkout›/build/**/gen/flapi/python` for an editable install that tracks rebuilds without reinstalling. This stays a one-time setup choice, not a per-run behavior.

**Version-match matters:** the installed wheel must match the `flapid` you connect to, so always source it from the same build root you are targeting. At runtime `conn.connect()` also needs auth (local token auto-resolved; remote needs a token from `fl-setup-flapi-token`).

## Context Strategy

Context comes from three kinds of source. No duplication between them.

### 1. Context sources (a generalized list, not a single repo)

Context comes from a list of sources recorded in `config.json` (see the config.json shape above). The cloned sibling FLAPI repo is the first source; the user can register additional local directories during init or later via `config add-source`. All sources are treated uniformly.

The first/default source, the sibling FLAPI repo (github.com/FilmLight/flapi, cloned on init, updated via git pull), contains:

- Official API documentation
- Example scripts (customer scripts, getting started examples)
- Integration examples (Frame.IO v4, slate detection, ML conform, multimodal search)
- API reference files
- Any community-contributed scripts

Extra `local` sources let a developer point the MCP at studio script collections or other FLAPI-rich folders.

On startup, the MCP server iterates every enabled source: it git-pulls each `git` source whose checkout exists, then walks each source tree and indexes filenames and content for keyword search. New examples added to any source become available after a restart (and a git pull, for git sources).

### 2. Local Baselight installation (discovered dynamically)

**Platform: macOS only for v1. Python only for v1** (the docs ship nodejs/java/javascript variants; we ignore them). Linux/`/usr/fl` support is deferred.

Two distinct trees, per the config split:

**A. Data root** (`/Library/Application Support/FilmLight/`) — runtime data, venvs, script dirs, prefs:

- **Active FLAPI Python:** `Baselight/blsiteprefs`. The key `flapi_python_path__Mac` (fallback `flapi_python_path`) names the base Python interpreter FLAPI uses.
- **Script venvs:** `python/<pyver>-v<blmajor>-venv/`, e.g. the current `3.12-v7-venv` (Python 3.12, Baselight 7); older builds use the legacy `<pyver>-venv` form (`3.11.6-venv`, `3.9.13-venv`). **Baselight creates and updates these itself on launch** (or via `fl-setup-flapi-scripts --create`); the MCP never creates one. The matching venv is the install target for application-script dependencies, resolved by matching `flapi_python_path__Mac` to the venv name. The `flapi` module + its deps are installed here as the `filmlightapi` wheel.
- **Application (UI) script directory:** `scripts/`.
- **Server script directory:** `server-scripts/`.

**B. Build roots** (`baselight_roots`, see config) — the installed app or a dev build/checkout:

- **flapi module / `filmlightapi` wheel:** under the root's `share/flapi/python` (path varies by `kind`). The wheel is `filmlightapi-<version>-py3-none-any.whl`. **Distinction: import name is `flapi`; pip/distribution name is `filmlightapi`.**
- **flapid binary** and **FLAPI JSON schema:** in the build tree.
- **Docs:** the `python/` and `common/` markdown under `flapi/docs/`, plus the generated `gen/doc/flapi/python.md` (full reference). See Context source #1.
- **Installed versions** are discovered per root (release roots scanned under `/Applications/Baselight/*`; dev roots are user-registered).

**C. Auth (per the docs, Baselight/Daylight 5.3+).** FLAPI connections require a username + token. Local connections resolve the token automatically for the current user. Remote connections need a username + token created via `fl-setup-flapi-token` on the server; the token is stored at macOS `~/Library/Preferences/FilmLight/flapi-token`. Camp A readiness checks token availability for remote targets.

This provides the ground truth API surface for the version the developer targets. The target build root and (for Camp B) version are developer choices, not a single autodetected value. Restarting after an upgrade re-discovers everything.

> **Note:** `blsiteprefs` is site-wide and currently holds a single `flapi_python_path`. The interpreter can also be set in Baselight Preferences → Advanced : API Server. Per-user/per-build overrides are a later refinement; v1 treats the site pref as source of truth.

### 3. MCP package itself (patterns and gotchas)

Tool-specific content that doesn't belong in the FLAPI repo:

- Pattern templates: canonical boilerplate for each script type (grouped by camp; see Script Taxonomy)
  - **Camp A (standalone):**
    - cli_script.py — headless command-line script (connect to flapid, do work, close)
    - flexi_script.py — script that triggers and manages Flexi effects
    - render_script.py — submitting render jobs via QueueManager
    - thumbnail_script.py — extracting frames via ThumbnailManager
  - **Camp B (application, deployed into the app's script dirs):**
    - gui_script.py — UI script with menu items via ApplicationManager → `scripts/`
    - server_script.py — background processing with server script pattern → `server-scripts/`
- Gotcha documents: known pitfalls with problem descriptions and solutions
  - release() after cancel() on FrameAnalysis
  - pip version ordering (3-component vs 4-component)
  - venv activation (Baselight's venv vs system Python)
  - flapid teardown (conn.close() is sufficient)
  - scene locking and concurrent access

## No Vectorization Needed

The corpus is small: ~30-40 FLAPI classes, ~50-100 example scripts, ~10 pattern templates, ~20 gotcha documents. Total maybe 200-300 files.

Lookup strategy:
- Class docs: direct file lookup by class name, or Python introspection of the installed package
- Pattern templates: direct file lookup by type
- Example search: keyword grep across all files in the cloned repo
- Gotcha lookup: keyword grep across gotcha documents
- API surface: introspection of the importable `flapi` module (or parsing the generated `python.md`)

Simple, fast, debuggable. No embedding model, no vector store, no ML infrastructure.

## Script Taxonomy: Two Camps

The single most important thing to establish before writing any FLAPI script is **which camp it belongs to**, because the two camps have completely different environments, lifecycles, and readiness requirements. A request like "turn Baselight scenes into a web page" is ambiguous until classified: it could be either camp. Classify first (scaffolding Phase 0), then run only the checks that camp needs.

### Camp A — Standalone scripts (run *outside* Baselight)

- Executed by an **external** Python interpreter (terminal, cron, CI).
- Reach a Baselight by connecting to a **flapid daemon** over the network.
- Do **not** require the desktop app to be running, only a reachable daemon.
- Pattern types here: `cli_script`, and standalone uses of `render_script` / `thumbnail_script` / `flexi_script`.
- **Readiness** (`check_standalone_readiness`): (1) a venv that can `import flapi` (the build-matching `filmlightapi` wheel installed), (2) flapid reachable or launchable, (3) auth token usable, (4) optional target job/scene.

### Camp B — Application scripts (run *inside* Baselight)

- Loaded by the **running application** from its configured Python venv, deployed into directories the app scans.
- Already hold an in-process FLAPI connection, so there is **no daemon probing**.
- Version- and venv-specific: multiple Baselight versions may be installed, each potentially bound to a different venv. The developer must pick the target version; the venv is then resolved from `blsiteprefs` (see discovery #2).
- Two sub-types, distinguished by **which directory the script is deployed to**:
  - **UI scripts** → `scripts/` — menu items, dialogs, event triggers (`gui_script`).
  - **Server scripts** → `server-scripts/` — background/long-running processing (`server_script`).
  - A project can include both.
- **Readiness** (`check_app_script_readiness(version, kind)`): (1) a target Baselight version is chosen, (2) its venv is resolved and exists, (3) the script's required dependencies are present in that venv (or installable via `install_dependencies`), (4) the destination script directory (`scripts/` or `server-scripts/`) exists and is writable.

### Classification decision tree (Phase 0, Claude-driven)

Claude routes the request before deep environment checks. It is not a tool; it is guidance Claude follows, asking the user when the request is ambiguous:

- **Q1.** Must it run inside a colorist's live Baselight session, add menu items/dialogs, respond to events, or run continuous background processing tied to the app? → **Camp B.** Otherwise, is it a task that connects to a Baselight, does its work, and exits? → **Camp A.**
- **Q2 (Camp B).** UI, server, or both? → selects `scripts/` vs `server-scripts/` and the `gui_script` / `server_script` pattern(s).
- **Q3 (Camp A).** Any task flavor (render submit, thumbnail extraction, flexi) that pulls in a specific pattern.

Worked example, "scenes → web page": ask Q1. "Run it from my terminal / nightly" → Camp A exporter. "A menu item in Baselight that exports the current scene" → Camp B UI. "Regenerate whenever scenes change" → Camp B server.

## MCP Tools

### Environment tools

Environment checks are **camp-aware**. The two `check_*_readiness` aggregators below are the entry points Claude calls after classification; the atomic checks beneath them are the primitives they compose (and Claude can call directly for diagnostics).

`check_standalone_readiness(hostname)` — **Camp A entry point**
- Aggregates the Camp A requirements: (1) a venv that can `import flapi` (the build-matching `filmlightapi` wheel installed); (2) flapid reachable **or** launchable; (3) auth — a usable token (auto for local, username+token for remote).
- flapid: the **common** mode is connecting to an already-running flapid (probe config host → localhost; if none, prompt for a hostname). The **rare** mode is `flapi.Connection().launch()`, which spawns a private child flapid from the build root, no running service needed; readiness reports this as a fallback when nothing is reachable.
- Returns: ready (bool), per-requirement status with remediation for anything missing.

`check_app_script_readiness(version, kind)` — **Camp B entry point**
- `kind ∈ ui | server | both`.
- Aggregates the Camp B requirements: the chosen Baselight `version` exists, its (Baselight-created) venv resolves and exists, the script's deps are present in that venv (or installable), and the destination directory (`scripts/` for ui, `server-scripts/` for server) exists and is writable. flapid here is the host Baselight process.
- Returns: ready (bool), resolved venv path, destination dir(s), remediation for anything missing.

`check_baselight_installation()` / `list_baselight_versions()`
- Enumerates versions across enabled `baselight_roots` (release roots scanned under `/Applications/Baselight/*`; dev roots as registered).
- Returns: versions with their root + kind, and the resolved `flapi`/wheel/flapid/docs paths per the layout template.
- Errors: no roots resolve, flapi module/wheel not found in a root.

`get_app_script_venv(version)`
- Resolves the Baselight-created venv: reads `blsiteprefs` (`flapi_python_path__Mac`, fallback `flapi_python_path`), matches to a `python/<pyver>-v<blmajor>-venv/` (or legacy `<pyver>-venv/`) directory.
- Returns: base Python path, resolved venv path, whether it exists, and whether `import flapi` works within it.
- Errors: prefs key missing, no matching venv directory (suggest `fl-setup-flapi-scripts --create`).

`get_flapi_wheel(root)`
- Resolves the `filmlightapi-*.whl` for any root kind (the single sanctioned install path), per the root's `kind` layout template + any `overrides`.
- Returns: absolute wheel path; used by standalone-venv setup (`pip install`) and to verify a venv has a build-matching flapi.

`install_dependencies(version_or_venv, packages)`
- Pip-installs `packages` into the resolved venv (never system Python, never another version's venv). For standalone client setup, also installs the `filmlightapi` wheel from the chosen root.
- Does **not** create venvs (Baselight owns the Camp B venv; for a standalone client venv, point at `fl-setup-flapi-scripts` or a user-created venv).
- Honors pip gotchas (version ordering, venv activation) in gotchas/.
- Returns: install log, resulting installed versions. Safety: only ever targets a resolved venv.

`check_flapid(hostname, version)`
- Attempts a FLAPI connection (default host: config/localhost), version-aware so it can report how to start that build's flapid or use `launch()` if unreachable.
- Returns: connected, Baselight version, available jobs.
- Errors: flapid not running (with start/launch remedy), connection refused, auth failure (with `fl-setup-flapi-token` remedy).
- (Camp A primitive — Camp B app scripts connect back to their parent FilmLight process instead.)

`check_python_environment()`
- Checks which Python is active and whether `import flapi` works
- Checks if running inside a Baselight script venv or another interpreter
- Returns: Python version, venv status, `flapi`/`filmlightapi` version
- Warns: if the flapi version doesn't match the targeted Baselight build

`list_jobs(hostname)`
- Connects to flapid, lists available jobs and scenes
- Returns: job names, scene names, last modified dates

`validate_scene(hostname, job, scene)`
- Checks if a specific scene exists and is accessible
- Returns: scene metadata, shot count, format info

### Context tools

`get_class_docs(class_name)`
- Prefers markdown: per-class `flapi/docs/common/<Class>.md` + `flapi/docs/python/` and the generated `build/**/gen/doc/flapi/python.md` (from `dev-source` roots / context sources). For `dev-build`/`release` roots only the rendered `doc/flapi/python.html` is present, so parse that. Python only; nodejs/java/javascript variants ignored.
- Falls back to introspecting the importable `flapi` module
- Returns: description, methods with signatures, parameter types, return types, working examples

`get_pattern(pattern_type)`
- Reads from the MCP package's patterns/ directory
- Pattern types: cli_script, gui_script, server_script, flexi_script, render_script, thumbnail_script
- Returns: complete working code with setup/teardown, comments explaining each section

`search_examples(query)`
- Keyword search across all files in every enabled context source (the cloned FLAPI repo plus any user-registered directories)
- Returns: matching file paths, relevant code snippets with context, and which source each match came from
- Searches: file names, comments, function names, class usage

`search_gotchas(query)`
- Keyword search across the MCP package's gotchas/ directory
- Returns: matching gotcha documents with problem description and solution

`get_api_surface()`
- Introspects the importable `flapi` module (or parses the generated `python.md` reference)
- Returns: summary of all available classes and their methods
- Useful for Claude to understand the full scope of what's possible

### Script tools

`create_script(path, content)`
- Writes a generated script to disk
- Sets executable permissions
- For **Camp B**, the destination is the app's script directory for the sub-type (`scripts/` for UI, `server-scripts/` for server) so the app can load it; for **Camp A**, the working directory. Claude resolves the destination from the camp before calling.
- Returns: file path

`run_script(path, args)`
- Executes a **Camp A** standalone script with the resolved venv interpreter, the venv into which the build-matching `filmlightapi` wheel and any third-party deps were installed, so `import flapi` resolves. No PYTHONPATH injection.
- Captures stdout, stderr, return code
- Returns: output and any errors
- Timeout: 30 seconds default (configurable)
- Safety: only runs scripts in a designated working directory
- Note: Camp B application scripts are loaded by the running Baselight, not executed here; use `test_script` for those, and verify behavior inside the app.

`test_script(path)`
- Runs syntax check (python -m py_compile) using the resolved venv interpreter
- Optionally runs with --dry-run or --test flag if supported (Camp A)
- Returns: pass/fail with details

### Repo tools

`update_repo()`
- Git-pulls every enabled `git` context source (the sibling FLAPI repo, and any other git sources the user registered)
- Re-indexes all enabled sources afterward
- Returns: per-source updated files and current commit hash; `local` sources are re-indexed but reported as not-pullable

## Scaffolding Flow

When a developer starts a conversation asking to build an FLAPI script, Claude should follow this sequence (guided by tool descriptions):

### Phase 0: Classify the camp (do this first)
Run the classification decision tree (see Script Taxonomy). Determine **Camp A (standalone)** vs **Camp B (application)**, and for Camp B the sub-type (ui / server / both). Ask the user when the request is ambiguous, the "scenes → web page" case must not be guessed. The camp decides which checks run in Phase 1 and which pattern is selected in Phase 3.

### Phase 1: Environment check (camp-specific)
- **Camp A:** call `check_standalone_readiness(hostname)`. It checks `import flapi`, flapid reachability (config host → localhost → prompt, or launch), and auth token. 
- **Camp B:** call `list_baselight_versions()`, have the user pick a target version, then call `check_app_script_readiness(version, kind)`. If the venv is missing dependencies the script will need, call `install_dependencies(version, packages)`.

If readiness fails, help the developer fix the environment (start flapid, choose a version, install deps) before writing code.

### Phase 2: Requirements gathering
Claude asks (guided by tool descriptions, not hardcoded):

1. What do you want to accomplish? (export, conform, metadata, rendering, analysis, etc.)
2. (Usually settled in Phase 0) Standalone or in-application? If in-application: UI, server, or both?
3. **Camp A:** which Baselight host and job/scene are you targeting? **Camp B:** which Baselight version, and what dependencies will the script need in its venv?

### Phase 3: Template selection
Based on the camp and sub-type, call get_pattern() for the right script type (Camp A: cli/render/thumbnail/flexi; Camp B: gui_script → `scripts/`, server_script → `server-scripts/`).

### Phase 4: Context injection
Based on the task, call get_class_docs() for relevant classes, search_examples() for similar scripts, and search_gotchas() for known pitfalls.

### Phase 5: Generate and test
Claude writes the script. Calls create_script() to save it. Calls test_script() or run_script() to verify. Iterates on errors.

## Tool Descriptions

Tool descriptions guide Claude's behavior. Each should include:
- What the tool does
- When Claude should call it
- What the return values mean
- How results connect to next steps

Example:
```
check_flapid: Check if a Baselight FLAPI service is reachable.
Call this early in any conversation about writing FLAPI scripts.
If this fails, help the user start flapid or verify the hostname before proceeding.
Returns connection status, Baselight version, and available jobs.
```

## What This Is NOT

- Not a cloud service. Runs locally only.
- Not a Baselight remote control (that's Erik's flapi_mcp). This helps you WRITE scripts, not execute Baselight operations directly.
- Not a documentation website. It's an active development tool.
- Not tied to any specific LLM provider. MCP is an open protocol.

## Build Steps — Implement in This Order

### Step 1: Basic MCP server with stdio transport
- Python MCP server that starts, registers tools, communicates via stdio
- CLI with init command that clones the sibling FLAPI repo
- One dummy tool to verify Claude Code can connect
- Test: add to .claude/mcp.json, verify Claude sees the tools

### Step 2: Discovery module (macOS)
- Scan `/Library/Application Support/FilmLight/Baselight/` for installed versions
- Parse `blsiteprefs` for `flapi_python_path__Mac`; resolve the matching `python/<pyver>-venv/`
- Locate the `scripts/` and `server-scripts/` directories
- Locate the importable `flapi` module (venv or build root's `share/flapi/python`); introspect classes and methods
- Implement list_baselight_versions(), check_baselight_installation(), get_app_script_venv(), check_python_environment()

### Step 3: Repo module
- Clone sibling FLAPI repo (github.com/FilmLight/flapi) on init to ~/.flapi-dev-mcp/repo/
- Git pull on startup or on-demand via update_repo()
- Walk repo tree, build file index for keyword search

### Step 4: Environment tools
- Implement check_flapid() with real FLAPI connection
- Implement list_jobs() and validate_scene()
- Implement install_dependencies() (pip into the resolved venv) and the camp-aware aggregators check_standalone_readiness() / check_app_script_readiness()
- Test: Claude can classify the camp and verify the matching environment before writing code

### Step 5: Context tools
- Write pattern templates for cli_script, gui_script, server_script
- Write gotcha documents for the top 10 known pitfalls
- Implement get_class_docs() (introspection + repo docs fallback)
- Implement get_pattern(), search_examples(), search_gotchas(), get_api_surface()

### Step 6: Script creation and testing
- Implement create_script(), test_script(), run_script()
- Safety: sandbox to working directory, timeout on execution
- Test: Claude can generate, save, and test a script end-to-end

### Step 7: Polish tool descriptions
- Iterate on tool descriptions to guide Claude through the scaffolding flow
- Test with real scenarios: "I want to export all shots as EXRs", "I want to add a menu item that grades selected shots"

## Notes

- Resilient to missing Baselight. If no Baselight is found, still works with repo context and bundled patterns. Useful for writing scripts offline.
- Resilient to missing repo. If init hasn't been run or clone failed, still works with local Baselight introspection and bundled patterns. Degrades gracefully.
- Class docs can be auto-generated from `flapi` module introspection (or by reusing the build's generated `python.md`). Consider a generate_docs command that creates markdown from the live API.
- run_script needs careful sandboxing. Never execute outside the working directory. Timeout all executions.
- Complementary to Erik's flapi_mcp. This helps you write scripts. Erik's runs them.
