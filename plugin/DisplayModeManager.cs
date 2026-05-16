using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using Rhino;
using Rhino.Display;
using Newtonsoft.Json.Linq;

namespace RhinoAIBridge
{
    public static class DisplayModeManager
    {
        // -----------------------------------------------------------------------
        // Preset base-mode map
        // -----------------------------------------------------------------------

        private static readonly Dictionary<string, string> PresetBaseMode =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { "diagram",     "Shaded"    },
            { "technical",   "Technical" },
            { "blueprint",   "Wireframe" },
            { "sketch",      "Artistic"  },
            { "axonometric", "Shaded"    },
            { "atmospheric", "Shaded"    },
            { "monochrome",  "Shaded"    },
            { "cutaway",     "Technical" },
        };

        // -----------------------------------------------------------------------
        // ApplyPresetDefaults
        // -----------------------------------------------------------------------

        /// <summary>
        /// Fills <paramref name="d"/> with default values for the given preset.
        /// Only sets keys that are not already present.
        /// </summary>
        private static void ApplyPresetDefaults(string presetName, Dictionary<string, object> d)
        {
            switch (presetName.ToLowerInvariant())
            {
                case "diagram":
                    SetDefault(d, "background_color",     "#FFFFFF");
                    SetDefault(d, "edge_color",           "#333333");
                    SetDefault(d, "edge_thickness",       2);
                    SetDefault(d, "silhouette_thickness", 0);
                    SetDefault(d, "show_edges",           true);
                    SetDefault(d, "show_silhouettes",     false);
                    SetDefault(d, "show_interior_edges",  true);
                    SetDefault(d, "shading_enabled",      true);
                    SetDefault(d, "use_object_color",     true);
                    break;

                case "technical":
                    SetDefault(d, "background_color",     "#FFFFFF");
                    SetDefault(d, "edge_color",           "#000000");
                    SetDefault(d, "edge_thickness",       1);
                    SetDefault(d, "silhouette_thickness", 2);
                    SetDefault(d, "show_edges",           true);
                    SetDefault(d, "show_silhouettes",     true);
                    SetDefault(d, "show_interior_edges",  true);
                    SetDefault(d, "shading_enabled",      false);
                    SetDefault(d, "use_object_color",     false);
                    break;

                case "blueprint":
                    SetDefault(d, "background_color",     "#0a1628");
                    SetDefault(d, "edge_color",           "#00CFFF");
                    SetDefault(d, "edge_thickness",       1);
                    SetDefault(d, "silhouette_thickness", 2);
                    SetDefault(d, "show_edges",           true);
                    SetDefault(d, "show_silhouettes",     true);
                    SetDefault(d, "show_interior_edges",  true);
                    SetDefault(d, "shading_enabled",      false);
                    SetDefault(d, "use_object_color",     false);
                    break;

                case "sketch":
                    SetDefault(d, "background_color",     "#FFFFFF");
                    SetDefault(d, "edge_color",           "#222222");
                    SetDefault(d, "edge_thickness",       1);
                    SetDefault(d, "silhouette_thickness", 3);
                    SetDefault(d, "show_edges",           true);
                    SetDefault(d, "show_silhouettes",     true);
                    SetDefault(d, "show_interior_edges",  true);
                    SetDefault(d, "shading_enabled",      false);
                    SetDefault(d, "use_object_color",     false);
                    break;

                case "axonometric":
                    SetDefault(d, "background_color",     "#FFFFFF");
                    SetDefault(d, "edge_color",           "#000000");
                    SetDefault(d, "edge_thickness",       1);
                    SetDefault(d, "silhouette_thickness", 2);
                    SetDefault(d, "show_edges",           true);
                    SetDefault(d, "show_silhouettes",     true);
                    SetDefault(d, "show_interior_edges",  true);
                    SetDefault(d, "shading_enabled",      true);
                    SetDefault(d, "use_object_color",     true);
                    break;

                case "atmospheric":
                    SetDefault(d, "background_color",     "#F5EDD8");
                    SetDefault(d, "edge_color",           "#5C4A32");
                    SetDefault(d, "edge_thickness",       1);
                    SetDefault(d, "silhouette_thickness", 2);
                    SetDefault(d, "show_edges",           true);
                    SetDefault(d, "show_silhouettes",     true);
                    SetDefault(d, "show_interior_edges",  false);
                    SetDefault(d, "shading_enabled",      true);
                    SetDefault(d, "use_object_color",     false);
                    break;

                case "monochrome":
                    SetDefault(d, "background_color",     "#FFFFFF");
                    SetDefault(d, "edge_color",           "#000000");
                    SetDefault(d, "edge_thickness",       0);
                    SetDefault(d, "silhouette_thickness", 2);
                    SetDefault(d, "show_edges",           false);
                    SetDefault(d, "show_silhouettes",     true);
                    SetDefault(d, "show_interior_edges",  false);
                    SetDefault(d, "shading_enabled",      true);
                    SetDefault(d, "use_object_color",     false);
                    break;

                case "cutaway":
                    SetDefault(d, "background_color",     "#FFFFFF");
                    SetDefault(d, "edge_color",           "#000000");
                    SetDefault(d, "edge_thickness",       2);
                    SetDefault(d, "silhouette_thickness", 3);
                    SetDefault(d, "show_edges",           true);
                    SetDefault(d, "show_silhouettes",     true);
                    SetDefault(d, "show_interior_edges",  true);
                    SetDefault(d, "shading_enabled",      false);
                    SetDefault(d, "use_object_color",     false);
                    break;
            }
        }

        private static void SetDefault(Dictionary<string, object> d, string key, object value)
        {
            if (!d.ContainsKey(key)) d[key] = value;
        }

        // -----------------------------------------------------------------------
        // CreateDisplayMode
        // -----------------------------------------------------------------------

        public static JObject CreateDisplayMode(JObject p, RhinoDoc doc)
        {
            try
            {
                string name = p["name"]?.ToString();
                if (string.IsNullOrWhiteSpace(name))
                    return Error("Parameter name is required.");

                if (!name.StartsWith("AI-", StringComparison.OrdinalIgnoreCase))
                    name = "AI-" + name;

                string preset   = p["preset"]?.ToString();
                string baseMode = p["base_mode"]?.ToString();

                var paramDict = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);

                if (!string.IsNullOrWhiteSpace(preset))
                    ApplyPresetDefaults(preset, paramDict);

                OverlayCallerParams(p, paramDict);

                string baseName = null;
                if (!string.IsNullOrWhiteSpace(baseMode))
                    baseName = baseMode;
                else if (!string.IsNullOrWhiteSpace(preset) &&
                         PresetBaseMode.TryGetValue(preset, out string pb))
                    baseName = pb;

                DisplayModeDescription source =
                    FindModeByName(baseName) ??
                    FindModeByName("Shaded") ??
                    DisplayModeDescription.GetDisplayModes().FirstOrDefault();

                if (source == null)
                    return Error("No base display mode found to clone.");

                Guid newModeId = DisplayModeDescription.CopyDisplayMode(source.Id, name);
                if (newModeId == Guid.Empty)
                    return Error("CopyDisplayMode failed for: " + name);

                DisplayModeDescription newMode = DisplayModeDescription.GetDisplayMode(newModeId);
                if (newMode == null)
                    return Error("GetDisplayMode failed after copy for: " + name);

                ApplyParamsToMode(newMode, paramDict);
                DisplayModeDescription.UpdateDisplayMode(newMode);

                string modeId = newModeId.ToString();

                var applied = new JObject();
                foreach (var kv in paramDict)
                    applied[kv.Key] = kv.Value != null ? kv.Value.ToString() : null;

                return new JObject
                {
                    ["status"]         = "ok",
                    ["mode_name"]      = name,
                    ["mode_id"]        = modeId,
                    ["applied_params"] = applied
                };
            }
            catch (Exception ex)
            {
                return Error("CreateDisplayMode exception: " + ex.Message);
            }
        }

        // -----------------------------------------------------------------------
        // ApplyDisplayMode
        // -----------------------------------------------------------------------

        public static JObject ApplyDisplayMode(JObject p, RhinoDoc doc)
        {
            try
            {
                string name = p["name"]?.ToString();
                if (string.IsNullOrWhiteSpace(name))
                    return Error("Parameter name is required.");

                DisplayModeDescription mode = FindModeByName(name);
                if (mode == null)
                    return Error(string.Format("Display mode {0} not found.", name));

                var vp = doc.Views.ActiveView?.ActiveViewport;
                if (vp == null)
                    return Error("No active viewport.");

                vp.DisplayMode = mode;
                doc.Views.Redraw();

                return new JObject
                {
                    ["status"]    = "ok",
                    ["mode_name"] = mode.LocalName,
                    ["mode_id"]   = mode.Id.ToString()
                };
            }
            catch (Exception ex)
            {
                return Error("ApplyDisplayMode exception: " + ex.Message);
            }
        }

        // -----------------------------------------------------------------------
        // ListDisplayModes
        // -----------------------------------------------------------------------

        public static JObject ListDisplayModes(JObject p, RhinoDoc doc)
        {
            try
            {
                var modes = DisplayModeDescription.GetDisplayModes();
                var arr   = new JArray();

                foreach (var m in modes)
                {
                    arr.Add(new JObject
                    {
                        ["name"]      = m.LocalName,
                        ["id"]        = m.Id.ToString(),
                        ["is_custom"] = m.LocalName.StartsWith("AI-", StringComparison.OrdinalIgnoreCase)
                    });
                }

                return new JObject
                {
                    ["status"] = "ok",
                    ["modes"]  = arr,
                    ["count"]  = arr.Count
                };
            }
            catch (Exception ex)
            {
                return Error("ListDisplayModes exception: " + ex.Message);
            }
        }

        // -----------------------------------------------------------------------
        // AdjustDisplayMode
        // -----------------------------------------------------------------------

        public static JObject AdjustDisplayMode(JObject p, RhinoDoc doc)
        {
            try
            {
                string name = p["name"]?.ToString();
                if (string.IsNullOrWhiteSpace(name))
                    return Error("Parameter name is required.");

                DisplayModeDescription mode = FindModeByName(name);
                if (mode == null)
                    return Error(string.Format("Display mode {0} not found.", name));

                var paramDict = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
                OverlayCallerParams(p, paramDict);

                if (paramDict.Count == 0)
                    return Error("No parameters provided to adjust.");

                ApplyParamsToMode(mode, paramDict);
                DisplayModeDescription.UpdateDisplayMode(mode);

                var updated = new JObject();
                foreach (var kv in paramDict)
                    updated[kv.Key] = kv.Value != null ? kv.Value.ToString() : null;

                return new JObject
                {
                    ["status"]         = "ok",
                    ["mode_name"]      = mode.LocalName,
                    ["mode_id"]        = mode.Id.ToString(),
                    ["updated_params"] = updated
                };
            }
            catch (Exception ex)
            {
                return Error("AdjustDisplayMode exception: " + ex.Message);
            }
        }

        // -----------------------------------------------------------------------
        // DeleteDisplayMode
        // -----------------------------------------------------------------------

        public static JObject DeleteDisplayMode(JObject p, RhinoDoc doc)
        {
            try
            {
                string name = p["name"]?.ToString();
                if (string.IsNullOrWhiteSpace(name))
                    return Error("Parameter name is required.");

                if (!name.StartsWith("AI-", StringComparison.OrdinalIgnoreCase))
                    return Error(string.Format(
                        "Safety check failed: only AI- modes can be deleted. Got: {0}.", name));

                DisplayModeDescription mode = FindModeByName(name);
                if (mode == null)
                    return Error(string.Format("Display mode {0} not found.", name));

                bool deleted = DisplayModeDescription.DeleteDisplayMode(mode.Id);
                if (!deleted)
                    return Error(string.Format("DeleteDisplayMode failed for {0}.", name));

                return new JObject
                {
                    ["status"]    = "ok",
                    ["mode_name"] = name
                };
            }
            catch (Exception ex)
            {
                return Error("DeleteDisplayMode exception: " + ex.Message);
            }
        }

        // -----------------------------------------------------------------------
        // CaptureIllustration
        // -----------------------------------------------------------------------

        public static JObject CaptureIllustration(JObject p, RhinoDoc doc)
        {
            try
            {
                string displayModeName = p["display_mode"]?.ToString();
                int    width           = p["width"]  != null ? (int)p["width"]  : 1600;
                int    height          = p["height"] != null ? (int)p["height"] : 1200;
                bool   restoreMode     = p["restore_mode"] == null || (bool)p["restore_mode"];
                string styleNotes      = p["style_notes"]?.ToString();

                var view = doc.Views.ActiveView;
                if (view == null)
                    return Error("No active view.");

                var vp = view.ActiveViewport;
                DisplayModeDescription previousMode = vp.DisplayMode;
                string modeUsed = previousMode?.LocalName ?? "unknown";

                if (!string.IsNullOrWhiteSpace(displayModeName))
                {
                    DisplayModeDescription requestedMode = FindModeByName(displayModeName);
                    if (requestedMode == null)
                        return Error(string.Format("Display mode {0} not found.", displayModeName));

                    vp.DisplayMode = requestedMode;
                    modeUsed       = requestedMode.LocalName;
                    doc.Views.Redraw();
                }

                var size   = new System.Drawing.Size(width, height);
                var bitmap = view.CaptureToBitmap(size);

                if (bitmap == null)
                    return Error("CaptureToBitmap returned null.");

                string base64;
                using (var ms = new MemoryStream())
                {
                    bitmap.Save(ms, System.Drawing.Imaging.ImageFormat.Png);
                    base64 = Convert.ToBase64String(ms.ToArray());
                }
                bitmap.Dispose();

                if (restoreMode && previousMode != null)
                {
                    vp.DisplayMode = previousMode;
                    doc.Views.Redraw();
                }

                var result = new JObject
                {
                    ["status"]            = "ok",
                    ["image_base64"]      = base64,
                    ["width"]             = width,
                    ["height"]            = height,
                    ["display_mode_used"] = modeUsed
                };

                if (!string.IsNullOrWhiteSpace(styleNotes))
                    result["style_notes"] = styleNotes;

                return result;
            }
            catch (Exception ex)
            {
                return Error("CaptureIllustration exception: " + ex.Message);
            }
        }

        // -----------------------------------------------------------------------
        // Internal helpers
        // -----------------------------------------------------------------------

        /// <summary>
        /// Reads caller-supplied optional parameters from <paramref name="p"/> and
        /// overlays them into the working dictionary.
        /// </summary>
        private static void OverlayCallerParams(JObject p, Dictionary<string, object> d)
        {
            TryOverlay(p, d, "background_color",     v => v.ToString());
            TryOverlay(p, d, "edge_color",           v => v.ToString());
            TryOverlay(p, d, "edge_thickness",       v => (int)v);
            TryOverlay(p, d, "silhouette_thickness", v => (int)v);
            TryOverlay(p, d, "show_edges",           v => (bool)v);
            TryOverlay(p, d, "show_silhouettes",     v => (bool)v);
            TryOverlay(p, d, "show_interior_edges",  v => (bool)v);
            TryOverlay(p, d, "shading_enabled",      v => (bool)v);
            TryOverlay(p, d, "use_object_color",     v => (bool)v);
        }

        private static void TryOverlay(JObject p, Dictionary<string, object> d,
                                       string key, Func<JToken, object> convert)
        {
            if (p[key] != null)
            {
                try   { d[key] = convert(p[key]); }
                catch { /* ignore malformed values */ }
            }
        }

        /// <summary>
        /// Applies a parameter dictionary to a DisplayModeDescription.
        /// Only touches properties whose keys are present in the dictionary.
        /// </summary>
        private static void ApplyParamsToMode(DisplayModeDescription mode,
                                              Dictionary<string, object> d)
        {
            var attr = mode.DisplayAttributes;

            if (d.TryGetValue("background_color", out object bgObj))
            {
                Color c = ParseColor(bgObj?.ToString());
                if (c != Color.Empty)
                {
                    // Set solid background color via the display attributes solid color.
                    // DisplayModeDescription exposes background through DisplayAttributes.
                    attr.SetFill(c);
                }
            }

            if (d.TryGetValue("shading_enabled", out object shadeObj) && shadeObj is bool shade)
                attr.ShadingEnabled = shade;

            if (d.TryGetValue("show_edges", out object seObj) && seObj is bool se)
                attr.ShowSurfaceEdges = se;



            if (d.TryGetValue("edge_thickness", out object etObj) && etObj is int et)
                attr.SurfaceEdgeThickness = et;


            if (d.TryGetValue("use_object_color", out object uocObj) && uocObj is bool uoc)
                attr.UseCustomObjectColor = uoc;

            if (d.TryGetValue("edge_color", out object ecObj))
            {
                Color c = ParseColor(ecObj?.ToString());
                if (c != Color.Empty)
                    attr.SurfaceEdgeColor = c;
            }
        }

        /// <summary>
        /// Parses a color from a hex string ("#RRGGBB", "#RGB") or a named color.
        /// Returns Color.Empty on failure.
        /// </summary>
        public static Color ParseColor(string s)
        {
            if (string.IsNullOrWhiteSpace(s))
                return Color.Empty;

            s = s.Trim();

            if (s.StartsWith("#"))
            {
                string hex = s.TrimStart('#');
                try
                {
                    // Expand shorthand #RGB to #RRGGBB
                    if (hex.Length == 3)
                        hex = string.Concat(
                            hex[0], hex[0],
                            hex[1], hex[1],
                            hex[2], hex[2]);

                    if (hex.Length == 6)
                    {
                        int r = Convert.ToInt32(hex.Substring(0, 2), 16);
                        int g = Convert.ToInt32(hex.Substring(2, 2), 16);
                        int b = Convert.ToInt32(hex.Substring(4, 2), 16);
                        return Color.FromArgb(r, g, b);
                    }
                }
                catch { /* fall through */ }
                return Color.Empty;
            }

            // Try a named color (e.g. "white", "black", "red")
            Color named = Color.FromName(s);
            return named.IsKnownColor ? named : Color.Empty;
        }

        /// <summary>
        /// Finds a DisplayModeDescription by name (case-insensitive).
        /// Returns null if not found.
        /// </summary>
        private static DisplayModeDescription FindModeByName(string name)
        {
            if (string.IsNullOrWhiteSpace(name))
                return null;

            // RhinoCommon built-in lookup (exact match first)
            var mode = DisplayModeDescription.FindByName(name);
            if (mode != null)
                return mode;

            // Manual case-insensitive scan across all modes
            return DisplayModeDescription.GetDisplayModes()
                .FirstOrDefault(m => string.Equals(
                    m.LocalName, name, StringComparison.OrdinalIgnoreCase));
        }

        private static JObject Error(string message) =>
            new JObject { ["status"] = "error", ["message"] = message };
    }
}
