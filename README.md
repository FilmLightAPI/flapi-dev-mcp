# FLAPI Developer MCP

A local MCP server that helps a coding agent write FLAPI (FilmLight Baselight and
Daylight API) Python scripts. It finds your Baselight and Daylight installs, sets
up the right Python environment, and gives the agent the API reference, working
examples and logs for the exact build you're running, so it writes scripts that
work instead of guessing. Tested with Claude Code, Antigravity and OpenCode, and
it works with any MCP-aware agent. Runs on macOS and Linux (FilmLight BL hosts),
Python only.

Requires Baselight or Daylight **7+** (the wheel-based FLAPI distribution
introduced in 7.0.0.24232). Both products can be installed side by side. The
tools always follow the build that's serving flapid right now, so switching
between Baselight and Daylight, or between versions, needs no reconfiguring.

See [docs/DESIGN.md](docs/DESIGN.md) for the design.


## Install

This ships as a [uv](https://docs.astral.sh/uv/) tool: uv builds an isolated
environment for the server and puts the `flapi-dev-mcp` command on your PATH, so
there's no venv to manage by hand.

```bash
# 1. Install uv if you don't have it:
#    macOS:  brew install uv     (or use the curl installer below)
#    Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install the server as a tool, straight from the git URL:
uv tool install git+https://github.com/FilmLightAPI/flapi-dev-mcp
uv tool update-shell                 # one-time: puts the command on PATH (restart your shell)

# 3. Onboard (discovers Baselight/Daylight, clones the examples repo, writes config):
flapi-dev-mcp init
```

Then register it with your agent (step 4, below).

The flow is the same on macOS and Linux. `init` detects the OS and finds the
right paths (`/Library/Application Support/FilmLight/...` on macOS, `/usr/fl/...`
on Linux, plus `/vol/.support/scripts` when present).

**FilmLight developers** working from a dev build: run `flapi-dev-mcp init --dev`
and give it your build's `.app` (or checkout) when asked. Start that build's
services first, and init will target it.


## Register with your agent

The server is the same for every agent. Only the registration differs. Use the
name `flapi-dev` and the command `flapi-dev-mcp`.

**Claude Code** (user scope, so it's available in every project):

```bash
claude mcp add --scope user flapi-dev flapi-dev-mcp
```

**Codex CLI:**

```bash
codex mcp add flapi-dev -- flapi-dev-mcp
```

or add this to `~/.codex/config.toml`:

```toml
[mcp_servers.flapi-dev]
command = "flapi-dev-mcp"
```

**OpenCode:** add this to `opencode.json` (in your project, or the global
`~/.config/opencode/opencode.json`):

```json
{
  "mcp": {
    "flapi-dev": { "type": "local", "command": ["flapi-dev-mcp"], "enabled": true }
  }
}
```

**Cursor:** add this to `~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project):

```json
{
  "mcpServers": {
    "flapi-dev": { "command": "flapi-dev-mcp" }
  }
}
```

**Antigravity:** open the Agent panel, click the `...` menu, choose **MCP Servers**,
then **Manage MCP Servers** and **View raw config**, and add:

```json
{
  "mcpServers": {
    "flapi-dev": { "command": "flapi-dev-mcp", "args": [], "env": {} }
  }
}
```


## Using it in a project

Setup is **one-time**. Then open your agent in any folder and ask it to write a
FLAPI script in plain English:

```bash
mkdir ~/my-flapi-script && cd ~/my-flapi-script
claude        # or codex, opencode, ...
```

For a standalone script, the agent puts that project's Python venv in the folder
as `.venv`, so each project stays self-contained. For an App Script, it deploys
into the folder Baselight or Daylight scans and reloads the app's scripts.

**Agents that don't read MCP server instructions** (some do, Claude Code does):
run this once in the project folder.

```bash
flapi-dev-mcp init-project
```

It writes the FLAPI instructions into `AGENTS.md`, the file most agents read
every session, between `flapi-mcp` markers. Re-running it updates the block in
place, and your own text in that file is never touched. If the project has a
`CLAUDE.md`, it adds an `@AGENTS.md` import to it.


## Updating

```bash
uv tool upgrade flapi-dev-mcp        # pulls the latest release
# if a change doesn't show up, force a clean re-fetch:
uv tool install --reinstall git+https://github.com/FilmLightAPI/flapi-dev-mcp
```

Restart your agent afterwards so it starts the new server.


## Contributing

For development, an editable install in a local venv is convenient:

```bash
uv venv && uv pip install -e . && uv pip install pytest coverage
.venv/bin/python -m pytest tests                       # unit tests, no Baselight needed
FLAPI_LIVE=1 .venv/bin/python -m pytest tests/live     # install + init end to end, needs a running build
.venv/bin/python evals/run.py --label mine --runs 3    # agent evals against the running build
```

The evals run headless Claude Code sessions on plain-English FLAPI tasks against
a test job they create and remove themselves, and check the real results (marks
in the scene, stills on disk, App Scripts loaded in the app). See `evals/run.py`.
