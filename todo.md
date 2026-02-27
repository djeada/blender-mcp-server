## 1️⃣ Define Clear Architecture (Addon vs External Runtime)

* Decide:

  * Pure Blender add-on running MCP inside Blender
  * OR Blender add-on + external Python MCP runtime
* Define transport:

  * stdio (Claude Desktop style)
  * WebSocket
  * HTTP (less ideal for MCP tools)
* Define tool namespace:
  `blender.scene.*`, `blender.object.*`, `blender.material.*`

Deliverable:

* `/docs/architecture.md`
* Clean diagram
* Clear lifecycle: start server → register tools → respond → shutdown

---

## 2️⃣ Implement Core MCP Server Bootstrapping

* Implement MCP server initialization
* Register tool metadata properly (name, description, JSON schema)
* Handle:

  * request parsing
  * structured tool output
  * error handling
* Add graceful shutdown on Blender exit

Deliverable:

* `server.py`
* Tool registry system
* Logging system (very important for debugging)

---

## 3️⃣ Scene Inspection Tools (Read-Only First)

Start safe. Read-only tools are easiest.

Examples:

* `blender.scene.get_info`
* `blender.scene.list_objects`
* `blender.object.get_transform`
* `blender.object.get_hierarchy`
* `blender.material.list`

Make sure responses are structured JSON, not plain text.

---

## 4️⃣ Object Creation & Manipulation Tools

Add basic creation tools:

* `blender.object.create_cube`
* `blender.object.create_sphere`
* `blender.object.delete`
* `blender.object.translate`
* `blender.object.rotate`
* `blender.object.scale`
* `blender.object.duplicate`

Edge case handling:

* Object name conflicts
* Mode switching (Object/Edit)
* Active context safety

---

## 5️⃣ Material & Shader Tools

* `blender.material.create`
* `blender.material.assign`
* `blender.material.set_color`
* `blender.material.set_texture`
* Node tree manipulation

Avoid overexposing raw node graph initially — wrap common use cases first.

---

## 6️⃣ Rendering & Export Tools

Critical for real usage.

* `blender.render.still`
* `blender.render.animation`
* `blender.export.gltf`
* `blender.export.obj`
* `blender.export.fbx`

Include:

* Output path control
* Resolution override
* Render engine selection

---

## 7️⃣ Undo/Redo Safety Layer

Very important.

Implement:

* `blender.history.undo`
* `blender.history.redo`
* Automatic undo push before tool execution
* Safe rollback on tool failure

This prevents AI from destroying scenes irreversibly.

---

## 8️⃣ Security & Sandbox Guardrails

You **must** protect the environment.

* Prevent arbitrary `exec`
* Restrict file access to project directory
* Add optional “confirmation required” mode
* Add tool whitelist toggle

Add:

* `--safe-mode` flag

---

## 9️⃣ Testing Framework (Headless Blender)

Set up automated testing:

* Run Blender in background mode:

  ```
  blender -b --python test_runner.py
  ```
* Unit test:

  * Object creation
  * Tool JSON validation
  * Error cases
* CI workflow

Deliverable:

* `/tests`
* GitHub Actions workflow

---

## 🔟 Documentation & Developer Experience

Make it easy to adopt.

* Installation guide
* Claude Desktop config example
* Tool reference table
* Minimal example prompt
* Architecture diagram
* Contributing guide

Optional but powerful:

* Demo GIF
* Example AI session transcript

---

# Bonus 

* Add streaming tool responses
* Add scene diff tool (`blender.scene.diff`)
* Add geometry node manipulation
* Add multi-client support
* Add persistent session memory
* Add auto-generated tool schema from function decorators
