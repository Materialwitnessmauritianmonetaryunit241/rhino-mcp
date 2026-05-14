# RhinoAIBridge — AI Control of Rhino 8 via MCP

> **The most powerful Rhino MCP server.** Give Claude, ChatGPT, or Ollama full control of Rhino 8 — create geometry, manipulate layers, capture viewports, run any Rhino command, and more. No .NET SDK required on the target machine.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Rhino 8](https://img.shields.io/badge/Rhino-8.x-blue)](https://www.rhino3d.com/)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-green)](https://modelcontextprotocol.io/)
[![Works with Claude](https://img.shields.io/badge/Works%20with-Claude-orange)](https://claude.ai/)
[![Works with ChatGPT](https://img.shields.io/badge/Works%20with-ChatGPT-brightgreen)](https://openai.com/)
[![Works with Ollama](https://img.shields.io/badge/Works%20with-Ollama-purple)](https://ollama.com/)

---

## What is this?

**RhinoAIBridge** is a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that bridges any MCP-compatible AI — Claude Desktop, ChatGPT, or local Ollama models — directly into Rhino 3D (version 8). The AI can read your scene, create and modify geometry, manage layers, run scripts, capture viewport images, and execute any Rhino command — all from a natural language conversation.

This is the **fastest, most feature-complete Rhino AI integration available**:

- ⚡ **Sub-millisecond ping** with in-process scene cache (no full scene walks)
- 🗜️ **Gzip wire compression** — 5–8× smaller payloads on large scenes
- 📸 **Auto-thumbnails** — every mutation returns a viewport JPEG so the AI sees what it built
- ⚛️ **Atomic batches** — multi-step operations roll back as one unit on failure
- 🔌 **No .NET SDK required** on target machines — plugin is pre-built

---

## Quick Install (2 minutes)

**Requirements:** Rhino 8 · Python (auto-installed via uv) · Claude Desktop / ChatGPT API key / Ollama

### Windows

1. **Download** the latest release zip and unzip anywhere
2. **Double-click `INSTALL.bat`** — copies the plugin, installs dependencies, patches Claude Desktop config automatically
3. **Open Rhino 8** → type `PluginManager` → Install → browse to:
   `%APPDATA%\McNeel\Rhinoceros\8.0\Plug-ins\RhinoAIBridge\RhinoAIBridge.rhp`
   *(First time only — auto-loads on future starts)*
4. **In Rhino command line**, type: `AIBridge`
5. **Restart Claude Desktop** → ask: *"ping Rhino"*

That is it. No Visual Studio. No .NET SDK. No manual config editing.

For a detailed walkthrough see **INSTALL_GUIDE.txt**.

---

## 32 MCP Tools

### Scene & Context
| Tool | What it does |
|------|-------------|
| `ping` | Liveness check — returns doc name, unit system, object count, scene version |
| `query_scene` | Smart scene query: filter by type, layer, name, bbox, visibility |
| `get_object_details` | Full metadata for specific objects |
| `get_rhino_commands` | Discover all available Rhino commands with substring filter |

### Geometry Creation
| Tool | What it does |
|------|-------------|
| `create_object` | Universal create: Box, Cylinder, Sphere, Wall, Slab, Column, Roof, Curve, Point... |
| `create_massing` | Parametric building mass from footprint + height |
| `derive_floors_from_mass` | Auto-generate floor slabs by intersecting a massing solid |
| `create_core` | Structural core punched through a massing solid |
| `place_openings_on_facade` | Parametric window/door placement on any brep face |
| `get_cross_section` | Cut a section curve at any Z height |

### Modify & Transform
| Tool | What it does |
|------|-------------|
| `modify_object` | Change name, layer, colour, visibility, material |
| `transform_objects` | Move, rotate, scale, mirror, array |
| `boolean_operation` | Union, difference, intersection |
| `delete_objects` | Delete by ID list |

### Layers & Materials
| Tool | What it does |
|------|-------------|
| `create_layer` | Create layer with colour |
| `setup_arch_layers` | One-call layer stack: Site, Structure, Facade, Slab, Core, Roof... |
| `batch_layer_visibility` | Show/hide multiple layers at once |
| `set_layer_material` | PBR material: color, roughness, metallic, opacity, emission |

### Viewport & Capture
| Tool | What it does |
|------|-------------|
| `capture_viewport` | JPEG/PNG viewport image with auto-downscale + state restore |
| `set_view` | Switch to Top/Front/Right/Perspective/named view |
| `set_display_mode` | Wireframe, Shaded, Rendered, Ghosted, Arctic... |
| `set_camera` | Position camera by location+target or zoom to bounding box |
| `select_objects` | Highlight objects in the Rhino viewport |

### Analysis
| Tool | What it does |
|------|-------------|
| `measure_object` | Area, volume, bounding box, centroid |
| `measure_distance` | Distance between two points |
| `check_intersection` | Detect clashes between objects |
| `validate_objects` | Check for bad geometry / open edges |
| `report_areas` | Area schedule grouped by layer or type |

### Scripting & Workflow
| Tool | What it does |
|------|-------------|
| `run_command` | Execute any Rhino command string; returns new object IDs |
| `execute_script` | Run RhinoScript or Python code |
| `batch` | Send multiple operations as one atomic transaction |
| `undo` | Undo last operation |
| `get_log` | Inspect bridge command log with timestamps and timing |

---

## Connecting Different AI Providers

### Claude Desktop (recommended)
The installer patches `claude_desktop_config.json` automatically. Just restart Claude Desktop after install.

### ChatGPT
```
cd server
set OPENAI_API_KEY=sk-...
uv run python chat.py --provider openai --model gpt-4o
```

### Ollama (fully local, free)
```
ollama pull qwen2.5-coder:7b
cd server
uv run python chat.py --provider ollama --model qwen2.5-coder:7b
```
Best local models: `qwen2.5-coder:32b`, `deepseek-r1:32b`, `llama3.1:70b`

### Anthropic API directly
```
cd server
set ANTHROPIC_API_KEY=sk-ant-...
uv run python chat.py --provider anthropic --model claude-opus-4-6
```

---

## Architecture

```
Claude Desktop / ChatGPT / Ollama
         |  MCP (stdio)
         v
  server/src/rhino_architect/server.py   <- FastMCP Python server (32 tools)
         |  TCP 127.0.0.1:9544
         |  [1-byte flag][4-byte len][gzip payload]
         v
  plugin/RhinoAIBridge.rhp              <- C# Rhino 8 plugin
         |  UI thread dispatch + deferred redraw
         v
  Rhino 8 Document
```

**Wire protocol:** Responses over 10 KB are gzip-compressed. Large floor-stack responses see 5-8x reduction. The scene snapshot cache means repeated `query_scene` calls are O(1) regardless of object count.

**Atomic batches:** Send `batch(commands=[...], atomic=true)` and the entire sequence runs inside one Rhino undo record. Any failure triggers `Doc.Undo()` — the scene is left exactly as it was.

**Auto-thumbnails:** Every mutating tool captures a 240x180 JPEG after the viewport redraws and embeds it in the response. Claude sees the result immediately without a separate `capture_viewport` call.

---

## Building from Source

Only needed if you want to modify the C# plugin. Target machines do NOT need the .NET SDK.

Requirements: .NET 8 SDK, Rhino 8 (for RhinoCommon)

```
cd plugin
dotnet build --configuration Release
```

Output: `plugin/bin/Release/net8.0/`. Copy `.rhp` + DLLs to the Rhino plugin folder.

---

## Troubleshooting

**"Cannot connect to Rhino"** — Make sure Rhino is open and you have run the `AIBridge` command in Rhino's command line.

**Plugin does not appear in Claude** — Restart Claude Desktop after install. Check `%APPDATA%\Claude\claude_desktop_config.json` contains the `rhino-architect` server entry.

**uv not found** — Open a new terminal after install (PATH change does not apply to the current session).

**Ollama connection refused** — Run `ollama serve` in a separate terminal before starting `chat.py`.

**Large scenes slow** — Use `query_scene` with filters rather than fetching everything at once. The cache handles 5000+ objects at interactive speed.

---

## Changelog

### v4.5 (current)
- Pre-built plugin — no .NET SDK required on target machines
- `set_camera` with explicit location/target or bounding-box framing
- `get_rhino_commands` — live Rhino command discoverability
- `set_layer_material` — PBR properties (roughness, metallic, opacity, emission)
- `run_command` — execute any Rhino command string, returns new object IDs
- Auto-thumbnails on every mutation response
- Gzip wire compression (5-8x on large responses)
- `capture_viewport` restore_state — AI inspection never disrupts your view
- Atomic batch rollback with Doc.Undo() on failure

### v4.0
- Scene snapshot cache — O(1) reads regardless of object count
- Deferred redraw — batches fire one Redraw() instead of one per op
- Atomic batches with reference resolution ($1.object_ids[0])
- Architect intelligence: massing, floors, core, facade, schedules

---

## License

MIT — see LICENSE. Free for personal and commercial use.

---

*Built by Tanishq Bhattad — https://github.com/tanishqb*
