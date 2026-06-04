# A FLAPI coding harness — feeding a coding agent enough context to hit the ground running

A few of us have taken runs at MCPs to help people write FLAPI code. Erik's drives Baselight **directly** through FLAPI — skip the intermediary script entirely. Mine aims at a different job: an MCP that plugs into Claude Code and **quickly builds up the right context window** so the agent can hit the ground running and actually *produce* code — standalone scripts and app scripts you keep. Complementary to Erik's, not a redo.

This builds on our examples repo. The examples are great, but using one still takes a pile of *implicit* knowledge: which venv, how `flapi` actually gets installed, matching the wheel to your build, connecting to flapid + auth, where app scripts deploy, how to reload, where the logs are. That implicit layer is exactly what stops a newcomer — or an LLM — from just running an example. The MCP's whole job is to assemble that into the agent's context fast, so it starts from "ready."

Under the hood it's ~16 MCP tools the agent can call, grouped into stages:
- **Onboarding** (one-time `init`): clone the examples repo, discover the local install, write config.
- **Discovery:** is the environment ready to receive a script? — Baselight version, the right venv, flapid reachable, auth, script dirs. *(`flapi_status`, `check_standalone_readiness`, `check_app_script_readiness`, `check_flapid`)*
- **Context:** real class docs from the build's JSON schema + searchable repo examples + shipped examples, loaded into the agent's window. *(`get_class_docs`, `get_api_surface`, `search_examples`)*
- **Provisioning:** standalone → a per-project venv with the build-matching `flapi` wheel + deps (it even warns when the running flapid ≠ the build I'm targeting); app → deps into the managed venv + the right deploy dir. *(`setup_standalone_env`, `install_dependencies`, `install_app_dependencies`)*
- **Observation:** read logs and script output so the agent can self-correct. *(`get_flapi_log`, `get_app_script_log`)*

[SCREENSHOT 1 — onboarding / discovery](/user_uploads/2/fa/_IZPGx0g6xeBESmbHlsocMRr/Screenshot-2026-06-04-at-4.05.27PM.png)

Then it just works, in **two or three shots**, on genuinely complicated tasks. I had it turn a scene into a dialogue contact sheet:
- **Standalone:** a dark-theme **PDF** — scene path as a CLI arg so you can point it at any scene — Whisper transcription, a thumbnail per dialogue line at its midpoint with the line burned in.

[SCREENSHOT 2 — the standalone PDF](/user_uploads/2/d9/Zc8Sjw2IHDt7QdMuK2fibWdJ/Screenshot-2026-06-04-at-3.29.48PM.png)

- **App script:** the same idea, triggered in Baselight, that **backgrounds the Whisper transcription on the QueueManager** (with a progress dialog), pulls thumbs via the **ThumbnailManager**, and on completion stands up a web server and serves a dark **webpage** contact sheet. (That's the custom-queue-op + scene_to_webpage patterns I put in the repo, recombined by the agent.)

[SCREENSHOT 3 — the app-script webpage + the menu item](/user_uploads/2/7d/21EkEp4Pt3fVACcsTAjUac-3/Screenshot-2026-06-04-at-3.29.01PM.png)

It reasoned about the *constraint* on its own — it used **Export-stills** for the standalone (ThumbnailManager is app-only) and switched to **ThumbnailManager** for the app script. It backgrounded the slow job and added the progress UI with only light steering from me.

Where the human still sits: the loop is generate → run → **observe** → fix → repeat. Standalone loops freely — the agent runs the script itself. App scripts pause for me: you can't synthesize menu/button/dialog clicks, reloading is the gear-menu in practice, and restarting flapid to reload server scripts (or the daemon for standalone) is sudo-gated, so there's no clean one-command restart yet. That's fine for now — the agent converges, I just hit reload/click when it asks. Ungate those and you could hand an agent a *goal* and let it iterate hands-off.

To me this feels like demo material for the ongoing FLAPI workshops: closing with a live finale where it builds something complex in a couple of shots, in minutes.

## Try it yourself

macOS + Baselight + [uv](https://docs.astral.sh/uv/):

```

brew install uv # if you don't have it

git clone https://github.com/JasonMakes801/flapi-dev-mcp 

uv tool install ./flapi-dev-mcp && uv tool update-shell

flapi-dev-mcp init # discovers your Baselight, clones the examples repo, writes config

claude mcp add --scope user flapi-dev flapi-dev-mcp # register it with Claude Code so it appears in all your sessions

```

Then open Claude Code in any folder and just ask it to write a FLAPI script.

## Where this could go

I'm going to keep using it regardless — it's a genuine time saver. If people think it's worth it, it could live alongside the examples repo (a sibling in `FilmLightAPI`). **It clones the examples repo on setup and on update**, so the more scripts we stuff in there, the smarter this gets. It rides on the repo we're already growing.

One concrete thing that'd help right now: **a thumbnail example.** The agent worked `ThumbnailManager` out from the schema on its own, but an example would've gotten it there faster, so a thumbnail script in the repo directly speeds this up. That's the flywheel: every example we add makes the agent quicker and more reliable for everyone.

**Scope today: macOS, Baselight, and Claude Code only.** Obvious next steps if it's worth pursuing: add the Linux paths; support **Nara** as well as Baselight (for both); and reach other agents — the guidance it feeds in lives in `CLAUDE.md` files, which we'd translate into the formats Codex / Antigravity expect (`AGENTS.md` and friends). Early, mine, not official — happy to demo or share if anyone wants a look.