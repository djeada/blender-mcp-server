# Context benchmarks

A smaller tool list saves context. It does not follow that a model does better with it. This page measures both, and `scripts/context_benchmark.py` reproduces them.

```sh
python scripts/context_benchmark.py sizes                 # tool list bytes; no Blender
python scripts/context_benchmark.py trace --live          # fixed task sequences against a running Blender
python scripts/context_benchmark.py model --model qwen2.5:3b --budgets 4096,8192,32768   # local model
```

For `--live` and `model`, start a throwaway Blender with the bridge and set `BLENDER_MCP_PORT` and `BLENDER_MCP_TOKEN_FILE` to match it. Each task first deletes the scene's objects.

## Limits checked in CI

[`tests/context_budgets.json`](../tests/context_budgets.json) caps each profile's tool count and tool list bytes, discovery pages, action descriptions, guide cards and sections, workflow stages, recipe cards and the server-side bytes of five compact task traces. CI fails when one grows past its limit. Raise a limit only on purpose, and explain why.

## Fixed task traces

Each task is one fixed, successful tool sequence, replayed in both profiles. It shows what the **protocol** costs when a client makes no mistakes. It says nothing about whether a model finds that sequence. Measured against Blender 5.1.1; context bytes are the tool list plus all arguments and result text. Server instructions are empty (0 bytes). All ten runs passed every scene check, and compact results carried no duplicate structured copy.

| Task | Compact bytes | Calls | Full bytes | Calls |
|---|---:|---:|---:|---:|
| Basic prop | 14,119 | 12 | 68,813 | 5 |
| Stylized orc blockout | 16,695 | 12 | 67,838 | 4 |
| PBR material | 12,184 | 10 | 66,282 | 4 |
| Three-point lighting | 9,566 | 6 | 66,664 | 4 |
| Export | 8,154 | 4 | 65,389 | 2 |

Compact used 4 to 8 times fewer bytes and made 1.5 to 3 times as many calls. Images are counted separately because their token cost depends on the client. [Full data](benchmarks/trace-baseline.json).

## Small local model

`qwen2.5:3b` (3.1B parameters, Q4_K_M) on Ollama 0.30.8, temperature 0, seed 0, at most 14 turns, one run per cell, on three tasks that need no scripts. Model-written Python was disabled. Quality is the fraction of checks that pass **in the Blender scene**, whatever the model claims. This run used the server with 79 tools. [Full data](benchmarks/model-qwen2.5-3b.json).

| Context window | Profile | Basic prop | Lighting | Export | Mean |
|---|---|---:|---:|---:|---:|
| 8,192 | compact | 0.25 | 0.00 | 0.50 | 0.25 |
| 8,192 | full | does not fit | does not fit | does not fit | — |
| 16,384 | compact | 0.25 | 0.00 | 0.50 | 0.25 |
| 16,384 | full | 0.00 | 0.00 | 1.00 | 0.33 |
| 32,768 | compact | 0.25 | 0.00 | 1.00 | 0.42 |
| 32,768 | full | 0.00 | 0.50 | 1.00 | 0.50 |

Prompt sizes for this model, with a one-sentence task: **compact about 1,400 tokens, standard about 9,500, full about 10,700.**

### How this changed as tools were added

An earlier run of the same tasks, model and settings used a server with 62 tools. The full list was about 6,300 tokens then.

| Context window | Full, 62 tools | Full, 79 tools | Compact, 62 tools | Compact, 79 tools |
|---|---:|---:|---:|---:|
| 8,192 | 0.67 | does not fit | 0.25 | 0.25 |
| 32,768 | 0.92 | 0.50 | 0.58 | 0.42 |

Seventeen more tools pushed the full list past an 8,192 window, and `standard` with it. At 32,768 the full list scored much lower in this run. One run per cell cannot show that the extra tools caused that drop, but it is a reason to trim what a small model sees.

**What this shows:** a growing tool list costs real context, and this small model remains unreliable with either profile. Where the full list fit, it still scored at least as well as compact on average. It is poor at discovery: it often did not search at all, or invented names.

**What it does not show:** one run of one very small model on three tasks is not a ranking of profiles. Results moved a lot with small changes. In the 62-tool tests, compact lighting scored between 0.0 and 0.75 across runs that differed only in tool wording or window size, even at temperature 0. Larger models may behave very differently. Measure your model before choosing.

While building this benchmark, transcripts led to three changes: the search tool says what it can find, an early `invoke` returns the parameter list, and an unknown action ID suggests close real ones. Each addresses a failure that was observed. With this much variance, the runs do not show that they raised the scores.

## Choosing a profile

- **The full list fits with plenty of room to work** (for this model, a window of 16,000 tokens or more): `full` is the simplest. To trim it without losing direct calls, enable only the groups you need: `--profile compact --enable-groups materials,rendering`.
- **It does not fit:** use `compact`, and add the groups you use often with `--enable-groups` while there is room. Expect extra round trips and some tool-selection errors, and check results with `blender_mesh_inspect` and `blender_view_capture`.
- **Your client cannot change tool lists:** nothing to do; discovery uses a fixed list.

No profile guarantees that a particular small model will complete a task.

## Measurement notes

- The full list grows with every feature; check the current size with `python scripts/context_benchmark.py sizes`.
- Bytes are exact for the MCP messages. Clients may reformat schemas.
- `bytes / 4` is only a rough token estimate. For qwen2.5 on these schemas it **overstated** tokens by about half.
- The model benchmark uses the model server's own counts. Ollama silently truncates a prompt that exceeds its window, so before each turn the script measures the prompt in a large window and reports `context_overflow` instead of sending a request that would be cut. With `--api openai`, configure the server's window yourself.
- Image tokens vary by client and are not included.
