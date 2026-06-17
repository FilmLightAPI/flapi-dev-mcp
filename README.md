# FLAPI Developer MCP

A local MCP server for Claude Code that makes Claude an expert FLAPI (FilmLight
Baselight) developer. It discovers your local Baselight installation, gathers
FLAPI context, scaffolds scripts with the right boilerplate, and runs them to
verify they work. Supports macOS and Linux (FilmLight BL hosts), Python only.

See [CLAUDE.md](CLAUDE.md) for the full design spec.


## Install

This ships as a [uv](https://docs.astral.sh/uv/) tool: uv builds an isolated
environment for the server and puts the `flapi-dev-mcp` command on your PATH, so
there's no venv to manage by hand.

```bash
# 1. Install uv if you don't have it:
#    macOS:  brew install uv
#    Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
#    (either OS:  curl -LsSf https://astral.sh/uv/install.sh | sh)

# 2. Install the server as a tool, straight from the git URL:
uv tool install git+https://github.com/JasonMakes801/flapi-dev-mcp
uv tool update-shell                 # one-time: puts the command on PATH (restart your shell)

# 3. Onboard (discovers Baselight, clones the examples repo, writes config):
flapi-dev-mcp init

# 4. Register with Claude Code, user scope = available in every project:
claude mcp add --scope user flapi-dev flapi-dev-mcp
```

The flow is identical on macOS and Linux — `init` autodetects the OS and
resolves the right paths (`/Library/Application Support/FilmLight/...` on
macOS, `/usr/fl/...` on Linux, plus the cross-platform `/vol/.support/scripts`
when present).

## Using it in a project

Setup above is **one-time**. Because step 4 registers `flapi-dev` at **user scope**,
it's available in **every** Claude Code session automatically, there's nothing to
add or approve per project. To work on a new script:

```bash
mkdir ~/my-flapi-script && cd ~/my-flapi-script
claude        # flapi-dev is already here; just ask it to write a FLAPI script
```

(When the agent writes a *standalone* script, it puts that project's Python venv
right in the folder as `.venv`, so each project stays self-contained.)

## Updating

```bash
uv tool upgrade flapi-dev-mcp        # pulls the latest release
# if a change doesn't show up, force a clean re-fetch:
uv tool install --reinstall git+https://github.com/JasonMakes801/flapi-dev-mcp
```

## Contributing

For development, an editable install in a local venv is convenient:

```bash
uv venv && uv pip install -e .       # or: python3.12 -m venv .venv && .venv/bin/pip install -e .
```
