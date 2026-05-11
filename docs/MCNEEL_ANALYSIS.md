# McNeel RhinoMCP — Analysis & Competitive Strategy
*by tanishqb | RhinoAIBridge v4.5*

---

## What McNeel Built

McNeel's official [RhinoMCP](https://github.com/mcneel/RhinoMCP) (by Callum Sykes & Dan Cascaval) is a clean, well-designed foundation. Key facts:

- **11 tools** total
- **Pure C#** — no Python layer, uses the official `ModelContextProtocol.Server` NuGet package
- **HTTP/SSE transport** on `localhost:4862` (not stdio)
- **Yak package manager** distribution — zero-build install via `PackageManager` in Rhino
- MIT licensed, actively maintained by McNeel engineers

### Their 11 Tools
| Tool | What it does |
|---|---|
| `run_command` | Execute any Rhino command string via `RhinoApp.RunScript` |
| `run_python` | Execute Python 3 script via ScriptEditor, returns stdout/traceback |
| `list_objects` | List objects with name/layer/type filters |
| `get_viewport_image` | Capture viewport with optional view/camera/display-mode + `restoreState` |
| `get_selection` | Get currently selected objects |
| `set_selection` | Select objects by GUID |
| `get_commands` | Discover all registered Rhino command names (filterable) |
| `set_camera` | Set viewport camera — position, target, up, lens, projection, bbox framing |
| `probe_intersection` | Check if two objects intersect |
| `set_layer_material` | Set layer material (color, roughness, metallic, etc.) |
| `zoom_to_object` | Zoom viewport to a specific object |
| `zoom_to_layer` | Zoom viewport to all objects on a layer |

---

## What They Do Better Than Us (Gaps to Close)

### 1. `get_viewport_image` — `restoreState` parameter ⭐
McNeel's capture tool accepts `restoreState=true` (default). After capturing, it reverts the viewport to whatever view/display-mode/camera it was in before. This is excellent UX — the AI can "look at" the model from different angles for analysis without disrupting the user's current view.

**Our `capture_viewport`** has no such protection. If Claude switches to Top/Wireframe to grab a plan view, your Perspective/Shaded viewport is gone.

**Fix:** Add `restore_state: bool = True` to `CaptureInput` and the plugin handler. Save viewport state before any mutations, restore in a `finally` block.

### 2. `set_camera` — Bounding-box framing ⭐
McNeel's camera tool accepts `boxMin`/`boxMax` — the AI specifies what to frame, the tool computes the camera distance. Much better than forcing the AI to guess camera positions in 3D space.

**Our `set_view`** only switches named projections (Top, Perspective, etc.). No camera control.

**Fix:** Add a `set_camera` tool mirroring McNeel's signature.

### 3. `get_commands` — Rhino command discoverability
McNeel exposes `Command.GetCommandNames(true, false)` filtered by substring. This lets the AI discover that commands like `Contour`, `ProjectCurves`, `FilletEdge`, etc. exist before trying to call them via `run_command`.

We surface legacy commands through `rhino://capabilities` but they're hardcoded. McNeel's approach is live and complete.

**Fix:** Add `get_rhino_commands(filter?)` tool wrapping `Command.GetCommandNames`.

### 4. `run_command` — Surface as a first-class tool
We have `execute_script` as an escape hatch, but `run_command` (native Rhino command string execution) is more predictable for simple operations. McNeel surfaces it prominently.

We have it in our legacy commands callable inside `batch`, but not as a named MCP tool.

**Fix:** Add `run_command` to the 28-tool MCP surface.

### 5. `set_layer_material` — Rendering pipeline
McNeel supports setting layer materials (PBR: color, roughness, metallic, opacity, emission). We have zero material support.

For anyone doing Rendered or Arctic viewport work or Raytraced captures, this matters.

**Fix:** Add `set_layer_material` tool — low complexity, high value for visualization.

### 6. Yak Package Manager distribution
McNeel's install is literally: open Rhino → `PackageManager` → search `Rhino-MCP-Platform` → Install. Zero terminal, zero build tools.

We require .NET 8 SDK + a build step. Our `INSTALL.bat` improves this significantly, but we can't match Yak's simplicity without publishing to it.

**Fix:** Publish to Yak when the plugin is stable. Requires a McNeel developer account and signing. See https://developer.rhino3d.com/guides/yak/

### 7. HTTP/SSE transport
McNeel uses HTTP on port 4862. This means:
- One command to connect: `mcp add --transport http rhino http://localhost:4862`
- No JSON config file editing
- Could work over a network (not just localhost)

Our stdio transport requires editing `claude_desktop_config.json` (we automate this in `INSTALL.bat`, but it's still a less elegant connection model for Claude Code users).

**Fix:** Add an HTTP/SSE transport option alongside the existing stdio server. FastMCP supports SSE transport natively — it's a one-line change to the server entry point.

---

## What We Do Better (Advantages to Defend)

### 1. 28 tools vs 11 — architect intelligence layer
We have the entire architectural workflow: `derive_floors_from_mass`, `create_core` with punch-through, `place_openings_on_facade`, `align_to_grid`, `report_areas`. McNeel has none of this. Their approach is to let `run_command`/`run_python` handle everything complex — which works but requires the AI to write correct Rhino script from scratch every time.

### 2. Atomic batch with rollback + $N reference chaining
McNeel has no batching. Every operation is a separate round-trip. We can do 10 operations atomically in one call with reference resolution between steps. This is the single biggest workflow advantage.

### 3. Scene snapshot cache (O(1) scene queries)
McNeel queries the Rhino document directly on every `list_objects` call. We maintain an event-driven indexed cache. For scenes with hundreds of objects, our query is O(1) vs their O(N).

### 4. scene_version etag
Every response carries a `scene_version` counter. The AI can use it as an etag — skip re-querying a scene that hasn't changed. McNeel has no equivalent.

### 5. Multi-provider (Claude + ChatGPT + Ollama)
McNeel only supports MCP clients (Claude Desktop, Claude Code). Our `chat.py` works with any OpenAI-compatible API. Architects can use a local Ollama model for free, private use.

### 6. Deferred redraw (RedrawScope)
McNeel redraws after each operation. We batch all redraws to a single flush at the end of a command group. For a 20-floor building stack, this means 1 redraw vs 20. Rhino stays responsive.

### 7. JPEG viewport capture (in-memory, no disk)
McNeel writes a temp PNG file to disk. We encode JPEG directly in memory using `Graphics` + `EncoderParameters`. Faster, no temp file cleanup, and JPEG is typically 5-10× smaller than PNG for shaded views.

---

## Borrowed + Improved

### `restoreState` on viewport capture
Add to our `CaptureInput`. Implementation:

```csharp
// In CaptureViewport handler:
bool restore = p["restore_state"]?.ToObject<bool>() ?? true;
// Save state
var savedTarget = vp.CameraTarget;
var savedLocation = vp.CameraLocation;
var savedDisplayMode = vp.DisplayMode;

try {
    // ... do capture with any requested view/mode changes
}
finally {
    if (restore) {
        vp.SetCameraLocations(savedTarget, savedLocation);
        vp.DisplayMode = savedDisplayMode;
        view.Redraw();
    }
}
```

### `run_command` as a first-class tool
```python
# In server.py
@mcp.tool(name="run_command", annotations=WR)
async def run_command(params: RunCommandInput) -> dict:
    """Execute any Rhino command string. Escape hatch for commands not covered by structured tools."""
    return await _exec_simple("run_command", params.model_dump())
```

```csharp
// In CommandHandler.cs (already exists as a legacy command, just expose it)
_commands["run_command"] = W(p => {
    string cmd = p["command"]?.ToString() ?? "";
    RhinoApp.RunScript(cmd, false);
    return Ok(("executed", cmd));
});
```

### `get_rhino_commands` tool
```csharp
JObject GetRhinoCommands(JObject p)
{
    string filter = p["filter"]?.ToString() ?? "";
    var names = Rhino.Commands.Command.GetCommandNames(true, false)
        .Where(n => string.IsNullOrEmpty(filter) 
                 || n.Contains(filter, StringComparison.OrdinalIgnoreCase))
        .OrderBy(n => n)
        .Take(200)
        .ToArray();
    return new JObject { ["status"] = "ok", ["commands"] = new JArray(names), ["count"] = names.Length };
}
```

---

## Migration Strategy (Long-term)

As discussed in the handoff brief, Strategy 1 is the preferred path:

**Strategy 1 (~4 hours):** Fork McNeel's repo, add our 6 Phase 5 architect verbs as `IMcpTool` classes. Skip Phase 1/2/3 infrastructure. Get Yak distribution for free. Let McNeel maintain the transport layer.

**When to migrate:** When McNeel ships to Yak (~2-6 weeks from handoff). Confirm at https://discourse.mcneel.com/c/rhino/artificial-intelligence-rhino/

**What to port:**
- `create_object` (architect types: massing, core, wall, slab, column, opening, roof)
- `derive_floors_from_mass`
- `create_core` 
- `place_openings_on_facade`
- `align_to_grid`
- `report_areas`

**What to skip:** Phase 1 perf (RedrawScope, deferred redraw) — acceptable regression given Yak benefit.

**What can't be ported:** Atomic batch with $N reference chaining — McNeel's architecture doesn't support this without significant changes to their request-response model.

---

## Bugs Found in McNeel's Code

Worth filing upstream:

1. **`GetViewportImageTool.cs`** — The description says `Math.Max(width, 1280)` but the actual code correctly uses `Math.Min`. The description was the bug (it's fixed in the code). No action needed.

2. **`SetSelectionTool.cs`** — Uses `Task.Run + task.Wait()` around RhinoCommon calls. This can deadlock on Rhino's UI thread in some scenarios. Should use `RhinoApp.InvokeAndWait()` instead (as we do throughout our plugin).

3. **`RunPythonTool.cs`** — Writes scripts to `%TEMP%` and schedules deletion after 15 seconds. If Rhino is slow, the file might be deleted before the script finishes. Should delete after confirming execution.

---

*RhinoAIBridge v4.5 | by tanishqb | https://github.com/tanishqb/rhino-ai-bridge*
