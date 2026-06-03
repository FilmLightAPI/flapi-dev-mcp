# FLAPI Developer MCP

A local MCP server for Claude Code that makes Claude an expert FLAPI (FilmLight
Baselight) developer. It discovers your local Baselight installation, gathers
FLAPI context, scaffolds scripts with the right boilerplate, and runs them to
verify they work. macOS + Python only for v1.

See [CLAUDE.md](CLAUDE.md) for the full design spec.

## Status

Step 1 (skeleton) is in place: a stdio MCP server exposing a single `flapi_dev_ping`
connectivity tool, plus a CLI with stubbed `init` / `update` / `config` subcommands.

## Install (macOS, via uv)

This ships as a [uv](https://docs.astral.sh/uv/) tool: uv builds an isolated
environment for the server and puts the `flapi-dev-mcp` command on your PATH, so
there's no venv to manage by hand.

```bash
# 1. Install uv if you don't have it:
brew install uv                      # or: curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install the server as a tool (from a clone, or once published, a git URL):
uv tool install .                    # run from the cloned repo
uv tool update-shell                 # one-time: ensures the command is on PATH (restart your shell)

# 3. Onboard (discovers Baselight, writes ~/.flapi-dev-mcp/config.json):
flapi-dev-mcp init

# 4. Check it:
flapi-dev-mcp status
```

## Using from Claude Code

`.mcp.json` at the repo root registers the server as `flapi-dev` via the
`flapi-dev-mcp` command (on PATH after `uv tool install`). Open this project in
Claude Code, approve the project MCP server, and ask Claude to call
`flapi_dev_ping` to confirm connectivity.

## Contributing

For development, an editable install in a local venv is convenient:

```bash
uv venv && uv pip install -e .       # or: python3.12 -m venv .venv && .venv/bin/pip install -e .
```
