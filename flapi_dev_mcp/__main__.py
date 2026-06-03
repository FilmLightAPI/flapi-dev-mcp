"""Entry point: `python -m flapi_dev_mcp [subcommand]`.

With no subcommand, starts the MCP server over stdio (how Claude Code launches it).
With a subcommand (init / update / config), dispatches to the CLI.
"""

from flapi_dev_mcp.cli import main

if __name__ == "__main__":
    main()
