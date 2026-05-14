// RhinoAIBridge v4.6 -- TrustManager.cs
// 3-tier trust levels + session auth token.
//
// TRUST LEVELS (set via RHINO_TRUST_LEVEL env var, default: trusted):
//   safe      -- block execute_script, run_command, delete_objects, boolean_operation
//   trusted   -- block execute_script, run_command  (recommended default)
//   developer -- nothing blocked
//
// AUTH TOKEN:
//   Generated once at server start. Saved to %APPDATA%\AIBridge\session.json.
//   Every request must include {"auth_token": "<token>", "type": "...", "params": {}}.
//   Ping without a token is allowed (returns auth_required hint).

using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;

namespace RhinoAIBridge
{
    public enum TrustLevel { Safe, Trusted, Developer }

    public static class TrustManager
    {
        // Commands blocked in Safe mode (everything below + these)
        private static readonly HashSet<string> _safeExtras = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "delete_objects",
            "boolean_operation",
        };

        // Commands always blocked unless Developer
        private static readonly HashSet<string> _alwaysBlocked = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "execute_script",
            "run_command",
        };

        public static TrustLevel Level { get; private set; } = TrustLevel.Trusted;
        public static string Token { get; private set; } = "";

        private static string SessionFile =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                         "AIBridge", "session.json");

        public static void Initialize()
        {
            // Determine trust level
            var envLevel = (Environment.GetEnvironmentVariable("RHINO_TRUST_LEVEL") ?? "").Trim().ToLowerInvariant();
            Level = envLevel switch
            {
                "safe"      => TrustLevel.Safe,
                "developer" => TrustLevel.Developer,
                _           => TrustLevel.Trusted,
            };

            // Backward-compat: RHINO_SAFE_MODE=1 maps to Safe
            if (Level == TrustLevel.Trusted)
            {
                var safeModeEnv = (Environment.GetEnvironmentVariable("RHINO_SAFE_MODE") ?? "").Trim().ToLowerInvariant();
                if (safeModeEnv is "1" or "true" or "yes") Level = TrustLevel.Safe;
            }

            // Generate auth token
            Token = GenerateToken();

            // Persist session.json
            try
            {
                var dir = Path.GetDirectoryName(SessionFile);
                if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
                var json = new JObject
                {
                    ["auth_token"]   = Token,
                    ["trust_level"]  = Level.ToString().ToLowerInvariant(),
                    ["generated_at"] = DateTime.UtcNow.ToString("o"),
                    ["port"]         = 9544
                };
                File.WriteAllText(SessionFile, json.ToString(Formatting.Indented));
                AIBridgeLogger.Log(LogLevel.INFO, "Trust", $"Trust={Level}, token saved to {SessionFile}");
            }
            catch (Exception ex)
            {
                AIBridgeLogger.Log(LogLevel.WARN, "Trust", $"Could not write session.json: {ex.Message}");
            }
        }

        private static string GenerateToken()
        {
            var bytes = new byte[16];
            System.Security.Cryptography.RandomNumberGenerator.Fill(bytes);
            return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
        }

        // Returns null if allowed, or an error JObject if blocked.
        public static JObject CheckCommand(string command)
        {
            if (Level == TrustLevel.Developer) return null;

            if (_alwaysBlocked.Contains(command))
                return BlockedErr(command, $"'{command}' requires trust_level=developer. Set RHINO_TRUST_LEVEL=developer.");

            if (Level == TrustLevel.Safe && _safeExtras.Contains(command))
                return BlockedErr(command, $"'{command}' is blocked in safe mode. Set RHINO_TRUST_LEVEL=trusted or developer.");

            return null;
        }

        // Returns null if token matches (or auth is not enforced), or an error JObject.
        public static JObject CheckToken(string requestToken)
        {
            if (string.IsNullOrEmpty(Token)) return null; // auth not initialized
            if (requestToken == Token) return null;        // match
            return new JObject
            {
                ["status"]      = "error",
                ["error_code"]  = "AUTH_FAILED",
                ["message"]     = "Invalid or missing auth_token. Read the current token from %APPDATA%\\AIBridge\\session.json.",
                ["recoverable"] = false
            };
        }

        private static JObject BlockedErr(string command, string hint) => new JObject
        {
            ["status"]      = "error",
            ["error_code"]  = "COMMAND_BLOCKED_BY_TRUST_LEVEL",
            ["message"]     = hint,
            ["command"]     = command,
            ["trust_level"] = Level.ToString().ToLowerInvariant(),
            ["recoverable"] = false
        };

        public static JObject StatusSummary() => new JObject
        {
            ["trust_level"]  = Level.ToString().ToLowerInvariant(),
            ["token_active"] = !string.IsNullOrEmpty(Token),
            ["session_file"] = SessionFile
        };
    }
}