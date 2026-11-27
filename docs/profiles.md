# Tool profiles and on-demand capabilities

Many clients put every tool's schema into the model's context. A profile chooses which tools the server advertises in `tools/list`. The default is `full`, so existing setups keep every tool name and schema.

| Profile | Advertised groups | Tools | Serialized `tools/list` |
|---|---|---:|---:|
| `compact` | `core` | 15 | 5.8 KB |
| `standard` | `core`, `scene`, `modeling`, `materials`, `lighting`, `rendering`, `knowledge` | 70 | 57.0 KB |
| `full` (default) | all | 79 | 65.0 KB |

Sizes are the bytes of the JSON `tools/list` result. A client may reformat schemas, and token counts depend on its tokenizer, so treat bytes as a way to compare profiles, not as a promise about a particular context window. A smaller list does not by itself make a model more capable; see the [benchmarks](benchmarks.md) before choosing. `standard` and `full` are now large (about 9,500 and 10,700 tokens for one measured model); for a smaller working set, start from `compact` and enable the groups you need. Reproduce them with `python scripts/context_benchmark.py sizes`.

## Groups

| Group | Contents |
|---|---|
| `core` | Status, scene overview, primitive objects, transforms and undo. Always available |
| `scene` | Hierarchy, duplicating, naming, parenting, collections, batches, redo, project files |
| `modeling` | Mesh diagnostics and modifier stacks |
| `materials` | Materials, PBR texture sets, slots and face regions, shader graphs, diagnostics and previews |
| `lighting` | Lighting rigs, lights, world environment, lighting inspection and color management |
| `animation` | Timeline and keyframes |
| `rendering` | Inspection views, camera framing, cameras, renders and exports |
| `knowledge` | [Modeling, surfacing and lighting guides and staged workflows](knowledge.md) |
| `recipes` | [Reviewed scripts run by ID](recipes.md) |
| `scripting` | Python execution and background jobs |

## Configure

| Command-line option | Environment variable | Meaning |
|---|---|---|
| `--profile` | `BLENDER_MCP_PROFILE` | `compact`, `standard` or `full` |
| `--enable-groups` | `BLENDER_MCP_ENABLE_GROUPS` | Extra groups to advertise, comma-separated |
| `--allow-groups` | `BLENDER_MCP_ALLOWED_GROUPS` | Limit on usable groups, advertised or on demand. `core` is always kept |

Options override the environment. The server does not guess a profile from a model's name. An unknown profile or group stops the server with an error.

A small-context client:

```json
{
  "mcpServers": {
    "blender": {
      "command": "/absolute/path/to/blender-mcp-server",
      "args": ["--profile", "compact"]
    }
  }
}
```

A full-feature client needs no options. A compact client that mostly models and never runs Python:

```json
{
  "mcpServers": {
    "blender": {
      "command": "/absolute/path/to/blender-mcp-server",
      "env": {
        "BLENDER_MCP_PROFILE": "compact",
        "BLENDER_MCP_ENABLE_GROUPS": "modeling",
        "BLENDER_MCP_ALLOWED_GROUPS": "scene,modeling,materials,lighting,rendering"
      }
    }
  }
}
```

## Use actions that are not advertised

When some allowed group is not advertised, the server adds four discovery tools.

1. `blender_capability_search` lists groups, or ranks action IDs for words such as `bevel edges`. Matching is local keyword scoring, so try plainer words when nothing matches.
2. `blender_capability_describe` returns up to three actions with parameters, prerequisites and permissions. Add `detail="schema"` for JSON schemas.
3. `blender_capability_invoke` runs an action with an `arguments` object. It uses the same validation and handler as a direct call and returns the same payload.
4. `blender_capability_reset` forgets what the session described, for one group or all.

```
blender_capability_search(query="bevel the edges")
blender_capability_describe(actions=["blender_object_add_modifier"])
blender_capability_invoke(action="blender_object_add_modifier",
                          arguments={"name": "Hilt", "modifier_type": "BEVEL"})
```

An unadvertised action must be described in the current session before it can run. An earlier `invoke` runs nothing: it fails with `discovery_required`, returns the parameter list and counts as the description, so a second call succeeds. An unknown action ID gets suggestions for close ones. Sessions do not share this state. Unlike a direct call, the dispatcher rejects parameter names the action does not have, so a typo cannot silently fall back to a default.

The tool list never changes while the server runs. Clients that cache it work unchanged, and no list-change notifications are sent. Discovery costs extra round trips. Choose `full`, or enable the groups you use often, when the model has room for them.

## Visibility is not permission

Profiles and discovery only change what a client is told about. The [shared policy](policy.md) and the add-on's preferences still authorize every command, including ones invoked through the dispatcher or a batch. Describing an action reports whether the server's policy allows it; Blender preferences can restrict it further.

To keep a group unusable, set `--allow-groups`. It applies to direct calls, search, describe, invoke, and each step of a batch. It limits which tools this server offers. If `scripting` is allowed, a script can do anything the policy lets Python do, so use `allow_python` in the shared policy to control script execution.

Calling a hidden tool directly fails with `tool_not_enabled`. A group outside `--allow-groups` fails with `permission_denied`.

## Compact output

The compact profile also keeps responses small. `--output compact` turns this on with another profile, and `--output full` turns it off.

- Results are sent once, as unindented JSON without a duplicate structured copy. Schemas omit generated titles and output schemas.
- `blender_status` returns a summary. `detail="full"` returns the complete lists.
- Object, material, collection, keyframe and job listings return one page with `total` and `next_offset`. `blender_object_get_hierarchy` returns a node-limited tree; request a node with `children_omitted` by name to continue. Blender builds only the requested page of the hierarchy and material, collection and object records. Pass `limit` or `max_nodes` for a different size.
- Long `stdout` and `stderr` keep their last characters, and `error` keeps twice as many, so the end of a traceback survives.
- A response that is still over the budget becomes a preview. Its `truncation` field gives the total size, what was left out and an `output_id`. Failed batch steps and error findings are never dropped by list limits.

`blender_output_read(output_id, path, offset, limit)` returns the rest without running the command again, which matters for scripts and batches that change the scene. `path` is dotted, such as `stdout` or `result.findings.0.ids`, and keys with dots such as `Cube.001` work. Follow `next_offset`. A part too big to return lists its keys, and a list item too big for a page is named in `item_too_large`. The server keeps each session's eight most recent truncated outputs (16 MB in total, in memory), and older IDs expire.

| Option | Environment variable | Default |
|---|---|---:|
| `--max-response-bytes` | `BLENDER_MCP_MAX_RESPONSE_BYTES` | 8000 (minimum 2000) |
| `--page-size` | `BLENDER_MCP_PAGE_SIZE` | 25 |
| `--log-tail-chars` | `BLENDER_MCP_LOG_TAIL_CHARS` | 2000 |

These are context budgets for text. They are separate from the 8 MB wire limit and from the [policy's](policy.md) execution limits. Bytes only approximate tokens, and the ratio depends on the tokenizer and the text; four bytes per token overstated the tool schemas by about half for one [measured model](benchmarks.md#measurement-notes).

### Measured responses

Result sizes in bytes, including the MCP result wrapper, measured against Blender 5.1.1 with 501 objects in 50 parent groups and 80 materials:

| Task | Full | Compact |
|---|---:|---:|
| `blender_status` | 8,886 | 746 |
| List objects | 174,589 | 2,329 |
| Scene hierarchy | 118,023 | 1,644 |
| List materials | 16,547 | 1,656 |
| Mesh inspection with regions and 100 sample IDs | 5,861 | 2,758 |
| Script printing 3,000 lines and returning 501 entries | 177,329 | 3,207 |
| Batch of 32 steps, one failing | 15,431 | 6,448 |

Compact listings return only the first page, so reading every record costs more round trips.
