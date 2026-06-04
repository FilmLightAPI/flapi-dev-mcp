# Zulip post outline — flapi > FLAPI Repository thread (working draft)

> Where: reply in the existing `flapi > FLAPI Repository` Zulip thread.
> Who: **me (Jason) → FilmLight coworkers** who already know FLAPI cold. NOT a blog,
> NOT a launch. A show-and-tell: "here's a harness I've been playing with."
> Voice: **first person, no royal "we."** The repo is the team's (Peter stewards it);
> I contributed a few scripts; the MCP is my own experiment on top of it.
> No "what is FLAPI", no marketing, no install-for-the-masses pitch.

---

## 1. Intro — framing by approach  (1 short para)
- A few of us have taken runs at MCPs to help people write FLAPI code.
- Erik's drives the app **directly** through FLAPI — skip the intermediary script
  entirely.
- My angle is different: an MCP that **plugs into a good coding agent** (Claude /
  Claude Code) and **quickly builds up the right context window** so the agent can
  hit the ground running and actually *produce the code* — standalone scripts and
  app scripts you keep, not one-off remote-control calls.
- (So: complementary to Erik's, not a redo — different goal.)

## 2. Why "build the context" is the whole game  (1 short para — the insight)
- This connects to our examples thread: the examples are great, but using one takes
  a pile of *implicit* knowledge — which venv, how `flapi` gets installed, matching
  the wheel to your build, connecting to flapid + auth, where app scripts deploy,
  how to reload, where the logs are.
- That implicit layer is exactly what stops a newcomer — or an LLM — from just
  running an example. The MCP's job is to assemble that into the agent's context
  fast, so it starts from "ready," not "what even is my environment."

## 3. How it works — the stages  (use these names; 1–2 lines each)
- **Onboarding** (one-time `init`): clone the examples repo, discover the local
  install, write config.
- **Discovery / probing:** "is the environment ready to receive a script?" —
  Baselight version, the right venv, flapid reachable, auth token, script dirs.
- **Context assembly:** load the real API (class docs from the build's JSON schema,
  the generated reference) + searchable repo examples into the agent's window.
- **Provisioning:** standalone → a per-project `.venv` with the *build-matching*
  `flapi` wheel + deps (and it flags when the running flapid ≠ the build I'm
  targeting); app → deps into Baselight's managed venv + the right deploy dir.
- **Observation:** read the logs and script output so the agent can see what
  happened and self-correct.
- → these set up the **iteration loop** (the closing section).

## 4. What it produced — in two or three shots, max  (the payoff; show artifacts)
- Headline metric: with tight prompting, **2–3 shots** got complicated, *working*
  scripts — minutes, not hours — from examples I hadn't pre-read.
- **Standalone — dialogue contact sheet, dark-theme PDF.** Takes a **scene path as a
  CLI arg** (point it at any scene), transcribes with Whisper, a thumbnail per
  dialogue line at its midpoint with the line **burned in**. *(screenshot of the PDF)*
- **App script — live web contact sheet.** A trigger that **backgrounds the Whisper
  transcription on the QueueManager** (with a progress dialog), pulls thumbs via the
  **ThumbnailManager**, and on completion **stands up a web server and serves the
  contact sheet as a dark webpage**. *(screenshot of the page + the menu item)*
  — note this is the custom-queue-op + scene_to_webpage patterns I contributed,
  recombined by the agent.
- **The smart beat worth calling out:** the agent reasoned about the *constraint*
  per camp — it used **Export-stills** for the standalone (ThumbnailManager is
  app-only) and switched to **ThumbnailManager** for the app script. It also
  backgrounded the long job and added progress UI largely on its own (light
  steering from me).

## 5. Close — the loop, and the human still in it (for now)  (the punchline)
- A good loop = generate → run → **observe** → fix → repeat until the script works.
  That's what the stages above are really for.
- **Standalone loops freely:** the agent runs the script itself, reads the output,
  and can grind autonomously to a working result.
- **App scripts are punctuated by human actions today** — honestly:
  - clicking menu items / buttons / dialogs can't be synthesized programmatically.
  - reloading app scripts is, in practice, a human gear-menu action (Views >
    Scripts > Reload Scripts).
  - restarting flapid to reload *server* scripts — or restarting the daemon for
    *standalone* — is **sudo-gated**, so there's no clean one-command restart yet.
- So for now the loop pauses for a few taps from me, and that's fine: the agent
  still converges, I just hit reload / click when it asks.
- **Future:** if we ungate those steps (a programmatic reload, an un-sudo'd
  restart, maybe synthetic UI events), you could hand a coding agent a *goal* and
  let it iterate hands-off until it lands a working script — no human in the loop.
  Worth exploring.
- **This is demo material.** It's exactly what we should be showing at the FLAPI
  events — and a great way to *close* a demo: a live **grand finale** where we hand
  it a goal and it builds a genuinely complex script in two or three shots, in
  minutes, in front of people.
- Tag: early / macOS / mine, not official. Happy to demo or share.

---

## Visuals (phases + artifacts, NOT the model "thinking")
1. **Onboarding:** `flapi-dev-mcp init` / `status` — discovered version, venv,
   script dirs, repo clone.
2. **A probe:** `check_standalone_readiness` showing ready + my real job list
   (proves it's hitting my actual Baselight); maybe the build-mismatch warning.
3. **Standalone artifact:** a page of the contact-sheet PDF.
4. **App artifact:** the dark webpage + a glimpse of the menu item in Baselight.
5. *(optional)* the transcription running as a QueueManager job.
- Deliberately NOT shown: screenshots of it one/two-shotting — show the outputs.

## Length
- Zulip, internal, skimmable: ~**400–600 words** carried by the 4–5 visuals.
- Layers as tight bullets; let the artifacts prove it. Coworkers will skim, then
  click the images.
