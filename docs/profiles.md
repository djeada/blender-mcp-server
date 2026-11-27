# Tool profiles and on-demand capabilities

Many clients put every tool's schema into the model's context. A profile chooses which tools the server advertises in `tools/list`. The default is `full`, so existing setups keep every tool name and schema.

| Profile | Advertised groups | Tools | Serialized `tools/list` |
|---|---|---:|---:|
| `compact` | `core` | 14 | 5.2 KB |
| `standard` | `core`, `scene`, `modeling`, `materials`, `lighting`, `rendering` | 49 | 32.8 KB |
| `full` (default) | all | 55 | 38.3 KB |

Sizes are the bytes of the JSON `tools/list` result. A client may reformat schemas, and token counts depend on its tokenizer, so treat bytes as a way to compare profiles, not as a promise about a particular context window. Reproduce them with `python scripts/measure_context.py`.

## Groups

| Group | Contents |
|---|---|
| `core` | Status, scene overview, primitive objects, transforms and undo. Always available |
| `scene` | Hierarchy, duplicating, naming, parenting, collections, batches, redo, project files |
| `modeling` | Mesh diagnostics and modifier stacks |
| `materials` | Materials and image textures |
| `lighting` | Lights |
| `animation` | Timeline and keyframes |
| `rendering` | Cameras, renders and exports |
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

An unadvertised action must be described in the current session before it can be invoked, otherwise the call fails with `discovery_required`. Sessions do not share this state. Unlike a direct call, the dispatcher rejects parameter names the action does not have, so a typo cannot silently fall back to a default.

The tool list never changes while the server runs. Clients that cache it work unchanged, and no list-change notifications are sent. Discovery costs extra round trips. Choose `full`, or enable the groups you use often, when the model has room for them.

## Visibility is not permission

Profiles and discovery only change what a client is told about. The [shared policy](policy.md) and the add-on's preferences still authorize every command, including ones invoked through the dispatcher or a batch. Describing an action reports whether the server's policy allows it; Blender preferences can restrict it further.

To keep a group unusable, set `--allow-groups`. It applies to direct calls, search, describe, invoke, and each step of a batch. It limits which tools this server offers. If `scripting` is allowed, a script can do anything the policy lets Python do, so use `allow_python` in the shared policy to control script execution.

Calling a hidden tool directly fails with `tool_not_enabled`. A group outside `--allow-groups` fails with `permission_denied`.

In the compact profile, results are sent once as unindented JSON without a duplicate structured copy, schemas omit generated titles and output schemas, and `blender_status` returns a summary. Pass `detail="full"` to `blender_status` for the complete lists.
