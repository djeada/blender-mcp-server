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
| Basic prop | 13,704 | 12 | 49,849 | 5 |
| Stylized orc blockout | 16,117 | 12 | 48,833 | 4 |
| PBR material | 11,835 | 10 | 47,318 | 4 |
| Three-point lighting | 9,225 | 6 | 47,589 | 4 |
| Export | 8,116 | 4 | 46,425 | 2 |

Compact used 3 to 6 times fewer bytes and made 1.5 to 3 times as many calls. Images are counted separately because their token cost depends on the client. [Full data](benchmarks/trace-baseline.json).

## Small local model

`qwen2.5:3b` (3.1B parameters, Q4_K_M) on Ollama 0.30.8, temperature 0, seed 0, at most 14 turns, one run per cell, on three tasks that need no scripts. Model-written Python was disabled. Quality is the fraction of checks that pass **in the Blender scene**, whatever the model claims. [Full data](benchmarks/model-qwen2.5-3b.json).

| Context window | Profile | Basic prop | Lighting | Export | Mean |
|---|---|---:|---:|---:|---:|
| 4,096 | compact | 0.25 | 0.00 (overflowed) | 0.50 | 0.25 |
| 4,096 | full | does not fit | does not fit | does not fit | — |
| 8,192 | compact | 0.25 | 0.00 | 0.50 | 0.25 |
| 8,192 | full | 0.00 | 1.00 | 1.00 | 0.67 |
| 32,768 | compact | 0.25 | 0.50 | 1.00 | 0.58 |
| 32,768 | full | 1.00 | 0.75 | 1.00 | 0.92 |

The full tool list plus the prompt was about 6,300 tokens for this model; compact was about 1,400.

**What this shows:** when the full list fit, this model did better with it, on average, at both window sizes where it fit. It is worse at discovery: it often did not search at all, or invented action names. Compact was the only profile that ran in 4,096 tokens, with low success.

**What it does not show:** one run of one very small model on three tasks is not a ranking of profiles. Results moved a lot with small changes. Lighting in compact scored between 0.0 and 0.75 across runs that differed only in tool wording or window size, even at temperature 0. Larger models may handle discovery far better. Measure your model before choosing.

While building this benchmark, transcripts led to three changes: the search tool says what it can find, an early `invoke` returns the parameter list, and an unknown action ID suggests close real ones. Each addresses a failure that was observed. With this much variance, the runs do not show that they raised the scores.

## Choosing a profile

- **The full list fits with room to work** (for this model, roughly 8,000 tokens or more): start with `full`. Consider `standard`, or `--allow-groups`, to trim it.
- **It does not fit:** use `compact`, and add the groups you use often with `--enable-groups` while there is room. Expect extra round trips and some tool-selection errors, and check results with `blender_mesh_inspect` and `blender_view_capture`.
- **Your client cannot change tool lists:** nothing to do; discovery uses a fixed list.

No profile guarantees that a particular small model will complete a task.

## Measurement notes

- Bytes are exact for the MCP messages. Clients may reformat schemas.
- `bytes / 4` is only a rough token estimate. For qwen2.5 on these schemas it **overstated** tokens by about half.
- The model benchmark uses the model server's own counts. Ollama silently truncates a prompt that exceeds its window, so before each turn the script measures the prompt in a large window and reports `context_overflow` instead of sending a request that would be cut. With `--api openai`, configure the server's window yourself.
- Image tokens vary by client and are not included.
