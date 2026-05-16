// RhinoAIBridge v4.7 — TracingManager.cs
// by tanishqb | https://github.com/tanishqb/rhino-ai-bridge
//
// Receives traced geometry from the Python PDF/image CV pipeline as JSON
// and materialises it as Rhino objects, organised on structured sub-layers.
// Called from CommandHandler via:
//   ["apply_traced_elements"] = W(ApplyTracedElementsCmd)
//   ["get_trace_layers"]      = W(GetTraceLayersCmd)
//   ["clear_trace_layers"]    = W(ClearTraceLayersCmd)
//
// Handler wrappers to add in CommandHandler.cs:
//   JObject ApplyTracedElementsCmd(JObject p) => TracingManager.ApplyTracedElements(p, Doc);
//   JObject GetTraceLayersCmd(JObject p)       => TracingManager.GetTraceLayers(p, Doc);
//   JObject ClearTraceLayersCmd(JObject p)     => TracingManager.ClearTraceLayers(p, Doc);

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using Newtonsoft.Json.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace RhinoAIBridge
{
    /// <summary>
    /// Converts traced geometry JSON (produced by the Python CV pipeline) into
    /// native Rhino objects placed on a structured layer hierarchy.
    ///
    /// Layer hierarchy created under <c>{prefix}</c>:
    /// <list type="bullet">
    ///   <item><c>{prefix}</c>             — parent  (grey)</item>
    ///   <item><c>{prefix}::Lines</c>      — cyan</item>
    ///   <item><c>{prefix}::Arcs</c>       — green</item>
    ///   <item><c>{prefix}::Polylines</c>  — blue</item>
    ///   <item><c>{prefix}::Text</c>       — yellow</item>
    ///   <item><c>{prefix}::REVIEW</c>     — red  (confidence below threshold)</item>
    /// </list>
    ///
    /// Coordinates in the JSON payload are expected to already be in model units;
    /// the Python side handles any mm-to-model-unit conversion before posting.
    /// </summary>
    public static class TracingManager
    {
        // ─────────────────────────────────────────────────────────────────────
        //  PUBLIC ENTRY POINTS
        // ─────────────────────────────────────────────────────────────────────

        /// <summary>
        /// Main entry point.  Parses <paramref name="p"/> and creates Rhino geometry
        /// for every element that passes the confidence threshold.  Elements whose
        /// confidence falls below the threshold are placed on the REVIEW sub-layer
        /// rather than being silently skipped.
        ///
        /// Expected JSON shape:
        /// <code>
        /// {
        ///   "elements": [
        ///     { "type": "line",     "x1":0, "y1":0, "x2":100, "y2":0, "confidence":0.95 },
        ///     { "type": "arc",      "cx":50, "cy":50, "r":25, "start_angle_deg":0, "end_angle_deg":90, "confidence":0.82 },
        ///     { "type": "polyline", "points":[[0,0],[10,5],[20,0]], "closed":false, "confidence":0.75 },
        ///     { "type": "text",     "text":"ROOM 1", "x":30, "y":30, "height":5, "angle_deg":0, "confidence":0.65 }
        ///   ],
        ///   "layer_prefix":         "Traced",
        ///   "confidence_threshold": 0.65,
        ///   "z_elevation":          0.0,
        ///   "source_file":          "floorplan.pdf",
        ///   "page_number":          1
        /// }
        /// </code>
        /// </summary>
        public static JObject ApplyTracedElements(JObject p, RhinoDoc doc)
        {
            try
            {
                // ── parse top-level parameters ────────────────────────────────
                var    elements  = p["elements"]  as JArray ?? new JArray();
                string prefix    = p["layer_prefix"]?.ToString() ?? "Traced";
                double threshold = p["confidence_threshold"]?.ToObject<double>() ?? 0.65;
                double z         = p["z_elevation"]?.ToObject<double>() ?? 0.0;
                string source    = p["source_file"]?.ToString() ?? string.Empty;
                int    page      = p["page_number"]?.ToObject<int>() ?? 0;

                // Human-readable source label returned in the response
                string sourceLabel = string.IsNullOrEmpty(source)
                    ? string.Empty
                    : (page > 0 ? $"{source} p.{page}" : source);

                // ── ensure layer hierarchy ────────────────────────────────────
                int idxParent    = EnsureLayer(doc, prefix,                  Color.Gray);
                int idxLines     = EnsureLayer(doc, $"{prefix}::Lines",     Color.Cyan,   idxParent);
                int idxArcs      = EnsureLayer(doc, $"{prefix}::Arcs",      Color.Green,  idxParent);
                int idxPolylines = EnsureLayer(doc, $"{prefix}::Polylines", Color.Blue,   idxParent);
                int idxText      = EnsureLayer(doc, $"{prefix}::Text",      Color.Yellow, idxParent);
                int idxReview    = EnsureLayer(doc, $"{prefix}::REVIEW",    Color.Red,    idxParent);

                var layersCreated = new List<string>
                {
                    prefix,
                    $"{prefix}::Lines",
                    $"{prefix}::Arcs",
                    $"{prefix}::Polylines",
                    $"{prefix}::Text",
                    $"{prefix}::REVIEW"
                };

                // ── per-type counters ─────────────────────────────────────────
                int cLines = 0, cArcs = 0, cPolylines = 0, cText = 0, cReview = 0;

                // ── iterate elements ──────────────────────────────────────────
                foreach (JObject el in elements.OfType<JObject>())
                {
                    string type       = el["type"]?.ToString() ?? string.Empty;
                    double confidence = el["confidence"]?.ToObject<double>() ?? 1.0;
                    bool   lowConf    = confidence < threshold;

                    // Resolve the natural destination layer for this element type.
                    // Low-confidence objects are unconditionally routed to REVIEW.
                    int naturalIdx;
                    switch (type.ToLowerInvariant())
                    {
                        case "line":     naturalIdx = idxLines;     break;
                        case "arc":      naturalIdx = idxArcs;      break;
                        case "polyline": naturalIdx = idxPolylines; break;
                        case "text":     naturalIdx = idxText;      break;
                        default:         naturalIdx = idxReview;    break;  // unknown type → REVIEW
                    }

                    int targetIdx = lowConf ? idxReview : naturalIdx;

                    // Attempt geometry creation; silently skip on failure or unknown type.
                    bool added = false;
                    switch (type.ToLowerInvariant())
                    {
                        case "line":     added = AddLine(doc, el, z, targetIdx);     break;
                        case "arc":      added = AddArc(doc, el, z, targetIdx);      break;
                        case "polyline": added = AddPolyline(doc, el, z, targetIdx); break;
                        case "text":     added = AddText(doc, el, z, targetIdx);     break;
                        // Unrecognised types produce no geometry and are not counted.
                    }

                    if (!added) continue;

                    // Increment the appropriate counter.
                    if (lowConf)
                    {
                        cReview++;
                    }
                    else
                    {
                        switch (type.ToLowerInvariant())
                        {
                            case "line":     cLines++;     break;
                            case "arc":      cArcs++;      break;
                            case "polyline": cPolylines++; break;
                            case "text":     cText++;      break;
                        }
                    }
                }

                doc.Views.Redraw();

                int total = cLines + cArcs + cPolylines + cText + cReview;

                return new JObject
                {
                    ["status"] = "ok",
                    ["source"] = sourceLabel,
                    ["counts"] = new JObject
                    {
                        ["lines"]     = cLines,
                        ["arcs"]      = cArcs,
                        ["polylines"] = cPolylines,
                        ["text"]      = cText,
                        ["review"]    = cReview
                    },
                    ["total_elements"]       = total,
                    ["confidence_threshold"] = threshold,
                    ["layers_created"]       = new JArray(layersCreated.Cast<object>().ToArray())
                };
            }
            catch (Exception ex)
            {
                return Error(ex.Message);
            }
        }

        /// <summary>
        /// Returns every layer whose full path starts with <paramref name="p"/>["layer_prefix"],
        /// together with the number of Rhino objects on each layer.
        ///
        /// Expected JSON: <c>{ "layer_prefix": "Traced" }</c>
        /// </summary>
        public static JObject GetTraceLayers(JObject p, RhinoDoc doc)
        {
            try
            {
                string prefix = p["layer_prefix"]?.ToString() ?? "Traced";

                var result = new JArray();

                foreach (Layer layer in doc.Layers)
                {
                    if (layer.IsDeleted) continue;
                    if (!layer.FullPath.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) continue;

                    RhinoObject[] objs = doc.Objects.FindByLayer(layer);
                    int count = objs?.Length ?? 0;

                    result.Add(new JObject
                    {
                        ["layer"]        = layer.FullPath,
                        ["object_count"] = count,
                        ["color"]        = ColorToHex(layer.Color),
                        ["visible"]      = layer.IsVisible,
                        ["locked"]       = layer.IsLocked
                    });
                }

                return new JObject
                {
                    ["status"] = "ok",
                    ["prefix"] = prefix,
                    ["layers"] = result
                };
            }
            catch (Exception ex)
            {
                return Error(ex.Message);
            }
        }

        /// <summary>
        /// Deletes all objects that live on any layer whose full path starts with
        /// <paramref name="p"/>["layer_prefix"], then deletes those layers.
        /// All other geometry and layers are left completely untouched.
        ///
        /// Expected JSON: <c>{ "layer_prefix": "Traced" }</c>
        /// </summary>
        public static JObject ClearTraceLayers(JObject p, RhinoDoc doc)
        {
            try
            {
                string prefix = p["layer_prefix"]?.ToString() ?? "Traced";

                // Collect matching layers, deepest children first so that Rhino
                // does not complain about deleting non-empty parent layers.
                List<Layer> matchingLayers = doc.Layers
                    .Where(l => !l.IsDeleted &&
                                l.FullPath.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                    .OrderByDescending(l => l.FullPath.Length)
                    .ToList();

                if (matchingLayers.Count == 0)
                {
                    return new JObject
                    {
                        ["status"]          = "ok",
                        ["layers_deleted"]  = 0,
                        ["objects_deleted"] = 0,
                        ["message"]         = $"No layers found with prefix '{prefix}'."
                    };
                }

                int objsDeleted   = 0;
                int layersDeleted = 0;

                // Pass 1 — delete all objects on matching layers
                foreach (Layer layer in matchingLayers)
                {
                    RhinoObject[] objs = doc.Objects.FindByLayer(layer);
                    if (objs == null) continue;
                    foreach (RhinoObject obj in objs)
                    {
                        if (doc.Objects.Delete(obj.Id, true))
                            objsDeleted++;
                    }
                }

                // Pass 2 — delete layers (children already processed first)
                foreach (Layer layer in matchingLayers)
                {
                    if (doc.Layers.Delete(layer.Index, true))
                        layersDeleted++;
                }

                doc.Views.Redraw();

                return new JObject
                {
                    ["status"]          = "ok",
                    ["prefix"]          = prefix,
                    ["layers_deleted"]  = layersDeleted,
                    ["objects_deleted"] = objsDeleted
                };
            }
            catch (Exception ex)
            {
                return Error(ex.Message);
            }
        }

        // ─────────────────────────────────────────────────────────────────────
        //  GEOMETRY HELPERS
        // ─────────────────────────────────────────────────────────────────────

        /// <summary>
        /// Creates a <see cref="LineCurve"/> from element fields x1/y1/x2/y2
        /// at the given Z elevation and adds it to the document.
        /// Returns false if creation fails (e.g. degenerate line).
        /// </summary>
        private static bool AddLine(RhinoDoc doc, JObject el, double z, int layerIdx)
        {
            try
            {
                double x1 = el["x1"]?.ToObject<double>() ?? 0;
                double y1 = el["y1"]?.ToObject<double>() ?? 0;
                double x2 = el["x2"]?.ToObject<double>() ?? 0;
                double y2 = el["y2"]?.ToObject<double>() ?? 0;

                var curve = new LineCurve(new Point3d(x1, y1, z), new Point3d(x2, y2, z));
                if (!curve.IsValid) return false;

                doc.Objects.AddCurve(curve, MakeAttrs(layerIdx));
                return true;
            }
            catch { return false; }
        }

        /// <summary>
        /// Builds an <see cref="Arc"/> from cx/cy/r/start_angle_deg/end_angle_deg,
        /// converts to <see cref="ArcCurve"/>, and adds it to the document.
        ///
        /// Uses the <c>Arc(Plane, double, Interval)</c> overload: the plane origin
        /// is set to (cx, cy, z) so the arc centre lands at the correct position.
        /// Angles are converted from degrees to radians before passing to Rhino.
        /// </summary>
        private static bool AddArc(RhinoDoc doc, JObject el, double z, int layerIdx)
        {
            try
            {
                double cx       = el["cx"]?.ToObject<double>() ?? 0;
                double cy       = el["cy"]?.ToObject<double>() ?? 0;
                double r        = el["r"]?.ToObject<double>()  ?? 1;
                double startDeg = el["start_angle_deg"]?.ToObject<double>() ?? 0;
                double endDeg   = el["end_angle_deg"]?.ToObject<double>()   ?? 360;

                double startRad = startDeg * (Math.PI / 180.0);
                double endRad   = endDeg   * (Math.PI / 180.0);

                // WorldXY translated to the arc centre; keeps the arc in the XY plane.
                Plane plane = Plane.WorldXY;
                plane.Origin = new Point3d(cx, cy, z);

                var arc = new Arc(new Circle(plane, r), new Interval(startRad, endRad));
                if (!arc.IsValid) return false;

                doc.Objects.AddCurve(new ArcCurve(arc), MakeAttrs(layerIdx));
                return true;
            }
            catch { return false; }
        }

        /// <summary>
        /// Builds a <see cref="Polyline"/> from a JSON points array.
        /// Each point can be <c>[x, y]</c>, <c>[x, y, z]</c>, or <c>{"x":…,"y":…}</c>.
        /// When <c>closed</c> is true the first point is appended to close the loop.
        /// The polyline is converted to a NURBS curve before adding so that Rhino
        /// treats it as a standard curve object.
        /// </summary>
        private static bool AddPolyline(RhinoDoc doc, JObject el, double z, int layerIdx)
        {
            try
            {
                var rawPts = el["points"] as JArray;
                if (rawPts == null || rawPts.Count < 2) return false;

                bool closed = el["closed"]?.ToObject<bool>() ?? false;

                var pts = new List<Point3d>(rawPts.Count + 1);
                foreach (JToken pt in rawPts)
                {
                    double px = 0, py = 0, pz = z;
                    if (pt is JArray arr)
                    {
                        px = arr.Count > 0 ? arr[0].ToObject<double>() : 0;
                        py = arr.Count > 1 ? arr[1].ToObject<double>() : 0;
                        pz = arr.Count > 2 ? arr[2].ToObject<double>() : z;
                    }
                    else if (pt is JObject ptObj)
                    {
                        px = ptObj["x"]?.ToObject<double>() ?? 0;
                        py = ptObj["y"]?.ToObject<double>() ?? 0;
                        pz = ptObj["z"]?.ToObject<double>() ?? z;
                    }
                    pts.Add(new Point3d(px, py, pz));
                }

                // Append first point to close the loop if requested
                if (closed && pts.Count >= 2)
                    pts.Add(pts[0]);

                var polyline = new Polyline(pts);
                if (!polyline.IsValid) return false;

                NurbsCurve curve = polyline.ToNurbsCurve();
                if (curve == null || !curve.IsValid) return false;

                doc.Objects.AddCurve(curve, MakeAttrs(layerIdx));
                return true;
            }
            catch { return false; }
        }

        /// <summary>
        /// Creates a <see cref="TextEntity"/> at position (x, y, z) using the
        /// document's first dimension style.  The text plane is WorldXY translated
        /// to the insertion point and optionally rotated by <c>angle_deg</c> around Z.
        /// Falls back to a fresh <see cref="DimensionStyle"/> when the document
        /// has no styles (e.g. a blank file).
        /// </summary>
        private static bool AddText(RhinoDoc doc, JObject el, double z, int layerIdx)
        {
            try
            {
                string content  = el["text"]?.ToString() ?? string.Empty;
                double x        = el["x"]?.ToObject<double>()         ?? 0;
                double y        = el["y"]?.ToObject<double>()         ?? 0;
                double height   = el["height"]?.ToObject<double>()    ?? 1.0;
                double angleDeg = el["angle_deg"]?.ToObject<double>() ?? 0.0;

                if (string.IsNullOrEmpty(content)) return false;
                if (height <= 0) height = 1.0;

                // Build insertion plane: WorldXY origin translated to (x, y, z),
                // then rotated by angle_deg around the Z axis.
                Plane plane = Plane.WorldXY;
                plane.Origin = new Point3d(x, y, z);
                if (Math.Abs(angleDeg) > 1e-6)
                {
                    double rad = angleDeg * (Math.PI / 180.0);
                    plane.Rotate(rad, Vector3d.ZAxis);
                }

                // Use the document's first dim style; fall back to a default instance.
                DimensionStyle dimStyle = doc.DimStyles.Count > 0
                    ? doc.DimStyles[0]
                    : new DimensionStyle();

                // TextEntity.Create(text, plane, dimStyle, wrapped, rectWidth, rotationRadians)
                TextEntity te = TextEntity.Create(content, plane, dimStyle, false, 0.0, 0.0);
                if (te != null) te.TextHeight = Math.Max(0.1, height);
                if (te == null) return false;

                doc.Objects.AddText(te, MakeAttrs(layerIdx));
                return true;
            }
            catch { return false; }
        }

        // ─────────────────────────────────────────────────────────────────────
        //  LAYER HELPER
        // ─────────────────────────────────────────────────────────────────────

        /// <summary>
        /// Ensures a layer with the given full path exists in the document.
        /// If the layer is absent it is created with <paramref name="color"/> and,
        /// when <paramref name="parentIdx"/> is non-negative, nested under that parent.
        /// Returns the layer table index (always &gt;= 0 on success).
        /// </summary>
        private static int EnsureLayer(RhinoDoc doc, string fullName, Color color, int parentIdx = -1)
        {
            // Fast path: layer already present.
            int existing = doc.Layers.FindByFullPath(fullName, -1);
            if (existing >= 0) return existing;

            // Short name is the segment after the last "::".
            string shortName = fullName.Contains("::")
                ? fullName.Substring(fullName.LastIndexOf("::") + 2)
                : fullName;

            var layer = new Layer
            {
                Name  = shortName,
                Color = color
            };

            if (parentIdx >= 0)
                layer.ParentLayerId = doc.Layers[parentIdx].Id;

            int idx = doc.Layers.Add(layer);

            // doc.Layers.Add returns -1 if the layer already exists (casing race).
            // A second lookup covers this edge case.
            if (idx < 0)
                idx = doc.Layers.FindByFullPath(fullName, -1);

            return idx;
        }

        // ─────────────────────────────────────────────────────────────────────
        //  UTILITY HELPERS
        // ─────────────────────────────────────────────────────────────────────

        /// <summary>
        /// Returns an <see cref="ObjectAttributes"/> instance with its layer index
        /// set to <paramref name="layerIdx"/> and colour inherited from the layer.
        /// </summary>
        private static ObjectAttributes MakeAttrs(int layerIdx) =>
            new ObjectAttributes
            {
                LayerIndex  = layerIdx,
                ColorSource = ObjectColorSource.ColorFromLayer
            };

        /// <summary>
        /// Formats a <see cref="Color"/> as a CSS hex string, e.g. <c>#FF0000</c>.
        /// </summary>
        private static string ColorToHex(Color c) => $"#{c.R:X2}{c.G:X2}{c.B:X2}";

        /// <summary>Wraps a message in the standard <c>{"status":"error"}</c> envelope.</summary>
        private static JObject Error(string msg) =>
            new JObject { ["status"] = "error", ["message"] = msg };
    }
}
