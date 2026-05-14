// RhinoAIBridge v4.5 -- BatchPlanner.cs
// Provides batch_preview (dry-run) and extended $ref resolution.

using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;

namespace RhinoAIBridge
{
    public static class BatchPlanner
    {
        private static readonly HashSet<string> _captureCommands = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            { "capture_viewport", "set_camera" };

        private static readonly HashSet<string> _destructiveCommands = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            { "delete_objects", "boolean_operation", "execute_script", "run_command" };

        public static JObject Preview(JArray commands, Dictionary<string, Func<JObject, JObject>> knownCommands)
        {
            var steps    = new JArray();
            var warnings = new JArray();
            int creates  = 0, deletes = 0;

            for (int i = 0; i < commands.Count; i++)
            {
                var cmd  = commands[i] as JObject;
                if (cmd == null) { steps.Add(StepErr(i+1, "null command")); continue; }
                var type = cmd["type"]?.ToString() ?? "";
                var step = new JObject { ["step"] = i+1, ["command"] = type, ["status"] = "valid" };

                if (string.IsNullOrEmpty(type))
                {
                    step["status"] = "invalid"; step["reason"] = "missing type";
                }
                else if (!knownCommands.ContainsKey(type) && type != "batch")
                {
                    step["status"] = "warning"; step["reason"] = $"unknown command '{type}'";
                    warnings.Add($"step {i+1}: unknown '{type}'");
                }
                else
                {
                    if (_destructiveCommands.Contains(type)) { step["warning"] = "destructive"; warnings.Add($"step {i+1}: '{type}' is destructive"); }
                    if (_captureCommands.Contains(type))     step["note"] = "capture -- consider capture_at_end:true";
                    if (type.StartsWith("create_") || type == "loft" || type == "sweep1" || type == "pipe") creates++;
                    if (type == "delete_objects") deletes++;
                }

                // Validate $refs
                var paramsStr = cmd["params"]?.ToString() ?? "";
                var refs = Regex.Matches(paramsStr, @"\$(\d+)");
                if (refs.Count > 0)
                {
                    var refList = new JArray();
                    foreach (Match m in refs)
                    {
                        int refStep = int.Parse(m.Groups[1].Value);
                        if (refStep >= i+1) { step["status"] = "invalid"; step["reason"] = $"$ref to future step ${refStep}"; }
                        refList.Add(m.Value);
                    }
                    step["resolves_refs"] = refList;
                }
                steps.Add(step);
            }

            return new JObject { ["status"] = "ok", ["step_count"] = commands.Count,
                ["estimated_creates"] = creates, ["estimated_deletes"] = deletes,
                ["warnings"] = warnings, ["steps"] = steps };
        }

        private static JObject StepErr(int step, string reason) =>
            new JObject { ["step"] = step, ["status"] = "invalid", ["reason"] = reason };

        // Extended $ref: $1, $1.field, $1.field[0], $1.object_ids, $1.object_ids[0]
        public static JToken ResolveExtendedRef(string raw, List<JObject> priorResults)
        {
            if (raw == null || !raw.StartsWith("$")) return null;
            var m = Regex.Match(raw, @"^\$(\d+)(?:\.([a-zA-Z_][a-zA-Z_0-9]*)(?:\[(\d+)\])?)?$");
            if (!m.Success) return null;
            int idx = int.Parse(m.Groups[1].Value) - 1;
            if (idx < 0 || idx >= priorResults.Count) return null;
            var result = priorResults[idx];
            if (!m.Groups[2].Success) return result;
            var token = result[m.Groups[2].Value];
            if (token == null) return null;
            if (m.Groups[3].Success && token is JArray arr)
            {
                int ai = int.Parse(m.Groups[3].Value);
                return ai < arr.Count ? arr[ai] : null;
            }
            return token;
        }

        // Walk all JTokens and resolve $ref strings
        public static JToken ResolveRefs(JToken token, List<JObject> priorResults)
        {
            if (token is JObject obj)
            {
                var r = new JObject();
                foreach (var p in obj.Properties()) r[p.Name] = ResolveRefs(p.Value, priorResults);
                return r;
            }
            if (token is JArray arr)
            {
                var r = new JArray();
                foreach (var item in arr) r.Add(ResolveRefs(item, priorResults));
                return r;
            }
            if (token is JValue val && val.Type == JTokenType.String)
            {
                var resolved = ResolveExtendedRef(val.ToString(), priorResults);
                return resolved ?? token;
            }
            return token;
        }
    }
}