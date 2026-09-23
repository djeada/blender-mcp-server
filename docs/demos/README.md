# Demos

Each demo below is a single prompt given to an AI client that was connected to a live Blender
through this MCP server. The render, the Blender screenshot, the list of tool calls and the agent's
reply were all captured from that run by [`scripts/record_demos.sh`](../../scripts/record_demos.sh).

| Demo | Shows | Recorded with |
|---|---|---|
| [1. Still life from a sentence](01-still-life.md) | Scene building, materials, Cycles render | Claude Code |
| [2. Procedural city with Python](02-procedural-city.md) | Generative Python via `blender_python_exec` | Codex |
| [3. Animate live, render headless](03-animation-headless.md) | Keyframes, saving, `transport="headless"` renders | Claude Code |

## Try them yourself

```bash
scripts/setup.sh
scripts/start.sh claude      # or: scripts/start.sh codex
```

Then paste a prompt from any demo page. Renders are written to `/tmp/blender-mcp-demos/`.

## Without an AI

Each demo has a matching Blender Python script in [`scripts/`](scripts/) that builds the same kind of
scene deterministically:

| Script | What it makes |
|---|---|
| [`01_still_life.py`](scripts/01_still_life.py) | Sphere, cube and torus on a ground plane, rendered with Cycles |
| [`02_procedural_city.py`](scripts/02_procedural_city.py) | Seeded 9x9 city block with streets, rendered with EEVEE (`--seed N`) |
| [`03_bouncing_ball.py`](scripts/03_bouncing_ball.py) | Keyframed squash-and-stretch bounce, saved to a .blend, frames rendered (`--frames ...`) |

```bash
scripts/run_demo.sh 2                    # open Blender, build and render (Blender stays open)
scripts/run_demo.sh --background 2       # just render, no window
scripts/run_demo.sh --bridge 2           # run it inside the Blender that scripts/start.sh opened
```

You can also paste any of them into Blender's **Scripting** tab and press **Run**.

## Re-record

```bash
scripts/record_demos.sh claude                              # every demo with Claude Code
scripts/record_demos.sh codex docs/demos/02-procedural-city.md
```

The recorder resets the scene, runs the prompt non-interactively through `scripts/start.sh`,
rewrites the "What the agent did" section, copies the renders into `images/` and screenshots the
Blender window. Results vary from run to run: the agents choose their own layouts, colours and camera angles.

Non-interactive runs pre-approve the Blender tools (`--allowedTools mcp__blender` for Claude Code, and
`--dangerously-bypass-approvals-and-sandbox` for `codex exec`), so only record in a Blender session
you are happy for the agent to change.
