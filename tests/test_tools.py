"""Guards the MCP's tool list and the descriptions agents choose tools by."""

from __future__ import annotations

import asyncio

from flapi_dev_mcp import server

EXPECTED = {
    "flapi_status", "get_api_surface", "get_class_docs", "search_examples",
    "check_standalone_readiness", "flapi_connection", "setup_standalone_env",
    "install_dependencies", "check_app_script_readiness", "create_app_venv",
    "install_app_dependencies", "reload_app_scripts", "get_app_script_log", "get_flapi_log",
}


def _tools():
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def test_tool_list_is_exactly_the_agreed_set():
    assert set(_tools()) == EXPECTED     # cut tools (ping, check_flapid, ...) stay cut


def test_descriptions_carry_the_key_rules():
    t = _tools()
    assert "doesn't exist in this build" in t["get_class_docs"].description
    assert "BEFORE writing any FLAPI script" in t["search_examples"].description
    assert "NOT for App Scripts" in t["install_dependencies"].description
    assert "never flapi.Application" in t["flapi_connection"].description
    assert "No Application class" not in t["flapi_connection"].description
    assert "restarted=false" in t["reload_app_scripts"].description


def test_instructions_fit_claude_codes_limit_and_carry_the_rules():
    from flapi_dev_mcp.instructions import INSTRUCTIONS
    assert server.mcp.instructions == INSTRUCTIONS
    assert len(INSTRUCTIONS) <= 1900          # Claude Code truncates at ~2,000
    for rule in ("check_standalone_readiness", "check_app_script_readiness", "search_examples",
                 "get_class_docs", "conn.Application.get()", "do_export_still",
                 "install_app_dependencies", "reload_app_scripts", ":1984", ":1985"):
        assert rule in INSTRUCTIONS, rule
    for tool in ("check_flapid", "flapi_dev_ping", "flapi_check_environment"):
        assert tool not in INSTRUCTIONS         # never point at a removed tool
