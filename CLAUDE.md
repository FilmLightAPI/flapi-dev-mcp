# flapi-dev-mcp: contributor notes

A local MCP server that helps coding agents write FLAPI (Baselight/Daylight API)
Python scripts. Design and history: `docs/DESIGN.md`. User setup: `README.md`.

## Layout

- `flapi_dev_mcp/server.py`: the 14 MCP tools (thin wrappers; their docstrings are what agents choose by)
- `flapi_dev_mcp/instructions.py`: the always-loaded agent instructions (keep under 1,900 chars)
- `flapi_dev_mcp/config.py`: config file, and `target_layout()`, which picks the build every tool uses
- `flapi_dev_mcp/discovery.py`: finds installs, layouts and the running build
- `venvs.py` / `flapi_conn.py`: standalone scripts. `app_scripts.py`: App Scripts
- `schema.py` / `search.py` / `repo.py`: API reference, example search, the examples repo
- `cli.py` / `arch.py` / `report.py` / `project.py`: `init`, `doctor`, `status`, `init-project` and friends

## Rules

- **Bump the version** (`pyproject.toml` and `__init__.py`) on every user-facing
  change. uv caches built wheels by version, so without a bump users get stale code.
- **Every change gets a regression test.** Run `.venv/bin/python -m pytest tests`.
- **Never fall back to another build** for a wheel, schema, venv or examples.
  Use `config.target_layout()`.
- **Agent-facing text is product code.** Tool docstrings and `instructions.py` decide
  whether agents use the tools well. Check changes with the evals.
- **Test like a user:** fresh install, plain-English prompts, real builds
  (release and dev). `tests/live` and `evals/run.py` do this.

## Evals

`evals/run.py --label <name> --runs 3 [--coverage]` runs headless Claude Code on
the prompts in `evals/prompts.json` against the running build, in a `flapi_eval`
job it creates and removes. It credits only calls in the build's schema. Results
go to `evals/results/<label>/` (gitignored). `--rescore` re-scores saved runs.
