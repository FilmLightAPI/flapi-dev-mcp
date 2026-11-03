"""The always-loaded agent instructions for this MCP.

Sent as the MCP server's `instructions`, which Claude Code puts in the system
prompt on every turn, and written into a project's AGENTS.md by
`flapi-dev-mcp init-project` for agents that ignore server instructions.

Keep it under 1,900 characters: Claude Code truncates server instructions at
about 2,000 (measured Nov 2026). Only specific, non-obvious rules belong here;
the tool descriptions carry the details.
"""

INSTRUCTIONS = """\
flapi-dev: tools for writing FLAPI (FilmLight Baselight/Daylight API) Python scripts. \
Use them for every FLAPI task and trust them over what you remember: FLAPI differs between builds.

Start: is it a standalone script (runs outside the app, connects to flapid :1984 or the \
live app :1985) or an App Script (runs inside the app: a UI menu/dialog, or a server \
script)? Ask if unclear.
- Standalone: check_standalone_readiness(project_dir=<cwd>), then flapi_connection to pick :1984 or :1985.
- App Script: check_app_script_readiness(kind) and follow its workflow.
Before writing code: search_examples("<keywords>") and read the top hit, then \
get_class_docs for every class you call. Not listed means it doesn't exist in this \
build: say so, don't invent it.

Rules:
- :1984 flapid is headless: open scenes by name, there is no current scene. :1985 is \
the running app: the open scene and the cursor.
- Application is an instance: app = conn.Application.get(). Never flapi.Application.<method>().
- conn.connect() before work, conn.close() after.
- Stills and thumbnails: Export.do_export_still with QueueManager.create_local, not ffmpeg.
- Standalone venv is <project_dir>/.venv. Always pass project_dir. Never system Python.
- App Script deps: install_app_dependencies, never install_dependencies.
- After deploying an App Script: reload_app_scripts(kind), then get_app_script_log (UI) \
or get_flapi_log (server). If reload says restarted=false, ask the user to reload.
- FLAPI can't toggle layers or edit strips and operators yet. It can add layers such as \
Base Grade or CDL.
"""
