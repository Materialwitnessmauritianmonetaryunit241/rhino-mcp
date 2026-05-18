// RhinoAIBridge v4.5 â€" AIBridgeServer.cs
// by tanishqb | https://github.com/tanishqb/rhino-ai-bridge

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Rhino;

namespace RhinoAIBridge
{
    /// <summary>
    /// TCP server. Length-prefixed JSON frames. One persistent UI-thread dispatcher
    /// instead of one ManualResetEvent per call. Async accept loop â€" no Sleep(100) tax.
    /// </summary>
    public class AIBridgeServer
    {
        private const int PORT = 9544;
        public const string PROTOCOL_VERSION = "4.6";

        private TcpListener _listener;
        private CancellationTokenSource _cts;
        private readonly object _lifecycleLock = new object();
        private bool _running;
        private readonly CommandHandler _handler = new CommandHandler();

        // Build hash captured once at startup â€" useful when 5 versions of the .rhp are on disk.
        public static string BuildHash { get; private set; } = ComputeBuildHash();

        public bool IsRunning => _running;

        private static string ComputeBuildHash()
        {
            try
            {
                var asm = Assembly.GetExecutingAssembly();
                var loc = asm.Location;
                if (string.IsNullOrEmpty(loc) || !File.Exists(loc)) return "unknown";
                using var s = File.OpenRead(loc);
                using var md5 = System.Security.Cryptography.MD5.Create();
                var bytes = md5.ComputeHash(s);
                return BitConverter.ToString(bytes, 0, 4).Replace("-", "").ToLowerInvariant();
            }
            catch { return "unknown"; }
        }

        private static void Diag(string msg)
        {
            try
            {
                var f = Path.Combine(Path.GetTempPath(), "aibridge_diag.txt");
                System.IO.File.AppendAllText(f, $"[{DateTime.Now:HH:mm:ss.fff}] Server.{msg}\n");
            }
            catch { }
        }

        public void Start()
        {
            Diag("Start() called");
            lock (_lifecycleLock)
            {
                if (_running) { RhinoApp.WriteLine($"AIBridge: Already running on 127.0.0.1:{PORT}  build:{BuildHash}"); return; }
                // NOTE: _running is NOT set here — only set after TCP listener opens successfully.
                // This prevents getting stuck in a fake-running state if any init step throws.
            }

            try
            {
                Diag("Calling AIBridgeLogger.Initialize");
                AIBridgeLogger.Initialize();

                Diag("Calling UiDispatcher.Start");
                UiDispatcher.Start();

                // SceneSnapshot registry must be initialized BEFORE the listener accepts clients.
                try
                {
                    if (RhinoApp.InvokeRequired)
                        RhinoApp.InvokeOnUiThread(new Action(() => SceneSnapshotRegistry.Initialize()));
                    else
                        SceneSnapshotRegistry.Initialize();
                }
                catch (Exception ex)
                {
                    Diag($"SceneSnapshot init failed (non-fatal): {ex.Message}");
                    AIBridgeLogger.Log(LogLevel.ERROR, "Server", "Snapshot registry init failed", error: ex.ToString());
                }

                try
                {
                    if (RhinoApp.InvokeRequired)
                        RhinoApp.InvokeOnUiThread(new Action(() => ChangeTracker.Initialize()));
                    else
                        ChangeTracker.Initialize();
                }
                catch (Exception ctEx)
                {
                    Diag($"ChangeTracker init failed (non-fatal): {ctEx.Message}");
                    AIBridgeLogger.Log(LogLevel.ERROR, "Server", "ChangeTracker init failed", error: ctEx.ToString());
                }

                Diag("Starting TcpListener");
                _listener = new TcpListener(IPAddress.Parse("127.0.0.1"), PORT);
                _listener.Start();
                _cts = new CancellationTokenSource();
                _ = Task.Run(() => AcceptLoop(_cts.Token));

                // Mark running ONLY after TCP is confirmed open.
                lock (_lifecycleLock) { _running = true; }
                Diag($"TcpListener started on port {PORT} -- marking running");

                // Run self-test and log results immediately.
                try
                {
                    var st = _handler.SelfTest();
                    Diag($"SelfTest: {st["message"]}");
                    AIBridgeLogger.Log(st["status"]?.ToString() == "ok" ? LogLevel.INFO : LogLevel.WARN,
                        "Server", $"SelfTest: {st["message"]}");
                }
                catch (Exception stEx) { Diag($"SelfTest threw: {stEx.Message}"); }

                RhinoApp.WriteLine("==================================================");
                RhinoApp.WriteLine("  Rhino AI Bridge v4.7 (C#)");
                RhinoApp.WriteLine($"  Listening on 127.0.0.1:{PORT}  build:{BuildHash}");
                RhinoApp.WriteLine("  Display modes, sections, materials, PDF tracing");
                RhinoApp.WriteLine("  Type AIBridgeStop to stop the server.");
                RhinoApp.WriteLine("  Logs: %APPDATA%\\AIBridge\\logs\\");
                RhinoApp.WriteLine("==================================================");
                AIBridgeLogger.Log(LogLevel.INFO, "Server", $"Started on 127.0.0.1:{PORT} build:{BuildHash}");
            }
            catch (Exception e)
            {
                Diag($"Start FAILED: {e.GetType().Name}: {e.Message}\n{e.StackTrace}");
                RhinoApp.WriteLine($"AIBridge: Failed -- {e.Message}");
                try { AIBridgeLogger.Log(LogLevel.ERROR, "Server", "Start failed", error: e.Message); } catch { }
                Stop();
            }
        }

        public void Stop()
        {
            lock (_lifecycleLock)
            {
                if (!_running) return;
                _running = false;
                try { _cts?.Cancel(); } catch { }
                try { _listener?.Stop(); } catch { }
                _listener = null;
            }
            UiDispatcher.Stop();
            try { SceneSnapshotRegistry.Shutdown(); } catch { }
            RhinoApp.WriteLine("AIBridge: Stopped");
            AIBridgeLogger.Log(LogLevel.INFO, "Server", "Stopped");
        }

        private async Task AcceptLoop(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested && _listener != null)
            {
                TcpClient client;
                try
                {
                    client = await _listener.AcceptTcpClientAsync(ct).ConfigureAwait(false);
                }
                catch (OperationCanceledException) { break; }
                catch (ObjectDisposedException) { break; }
                catch (Exception e)
                {
                    if (_running) AIBridgeLogger.Log(LogLevel.WARN, "Server", $"Accept error: {e.Message}");
                    continue;
                }

                // Fire-and-forget per-client task. Background thread.
                _ = Task.Run(() => HandleClient(client, ct));
            }
        }

        private void HandleClient(TcpClient client, CancellationToken ct)
        {
            var ep = client.Client.RemoteEndPoint?.ToString() ?? "?";
            AIBridgeLogger.Log(LogLevel.INFO, "Server", $"Client connected: {ep}");
            try
            {
                using (client)
                {
                    var stream = client.GetStream();
                    var hdr = new byte[4];
                    while (_running && client.Connected && !ct.IsCancellationRequested)
                    {
                        if (ReadExact(stream, hdr, 4) < 4) break;
                        int len = (hdr[0] << 24) | (hdr[1] << 16) | (hdr[2] << 8) | hdr[3];
                        if (len <= 0 || len > 50_000_000) break;     // cap: 50MB / frame

                        var buf = new byte[len];
                        if (ReadExact(stream, buf, len) < len) break;

                        var cmd = JObject.Parse(Encoding.UTF8.GetString(buf));
                        var timer = AIBridgeLogger.StartTimer();
                        string cmdType = cmd["type"]?.ToString() ?? "?";
                        JObject result;

                        try
                        {
                            // Fast path â€" ping is in-band, no UI thread hop.
                            if (cmdType == "ping")
                            {
                                result = HandlePing(cmd["params"] as JObject);
                            }
                            else
                            {
                                // Hop to UI thread, with deferred-redraw scope wrapping the dispatch.
                                result = UiDispatcher.Invoke(() =>
                                {
                                    using (RedrawScope.Defer())
                                    {
                                        var r = _handler.Dispatch(cmd);
                                        // Stamp the post-command scene version on every response.
                                        // Read tools see the version after any pending events have flushed;
                                        // mutating tools see the version reflecting their own changes.
                                        var snap = SceneSnapshotRegistry.Active;
                                        if (snap != null && r != null && r["scene_version"] == null)
                                            r["scene_version"] = snap.SceneVersion;
                                        return r;
                                    }
                                }, TimeSpan.FromSeconds(60));
                            }

                            // Batch commands store their payload in cmd["commands"], not cmd["params"],
                            // so log them separately to get something useful out of the log line.
                            string ps;
                            if (cmdType == "batch")
                            {
                                var cmds = cmd["commands"] as JArray;
                                bool atomic = cmd["atomic"]?.ToObject<bool>() ?? false;
                                int n = cmds?.Count ?? 0;
                                var types = cmds != null
                                    ? string.Join(", ", cmds.Take(6).Select(c => c["type"]?.ToString() ?? "?"))
                                    : "?";
                                ps = $"[{n} cmds, atomic={atomic}] {types}{(n > 6 ? "..." : "")}";
                            }
                            else
                            {
                                var paramStr = cmd["params"]?.ToString(Formatting.None) ?? "{}";
                                ps = paramStr.Length > 200 ? paramStr.Substring(0, 200) + "..." : paramStr;
                            }
                            AIBridgeLogger.LogCommand(cmdType, ps, timer,
                                result?["status"]?.ToString() ?? "?",
                                result?["message"]?.ToString());
                        }
                        catch (Exception e)
                        {
                            result = new JObject { ["status"] = "error", ["message"] = e.Message };
                            AIBridgeLogger.LogCommand(cmdType, "{}", timer, "error", e.ToString());
                        }

                        // â"€â"€ Serialize + optional gzip compression â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
                        // Protocol (server â†' client): [1-byte flag][4-byte big-endian length][payload]
                        //   flag 0x00 = raw UTF-8 JSON
                        //   flag 0x01 = gzip-compressed UTF-8 JSON
                        // Compress when payload > 10 KB â€" typical gains: 5-8Ã-- on object lists,
                        // ~2Ã-- on base64 image data. CompressionLevel.Fastest keeps CPU cost low.
                        const int GzipThreshold = 10_000;
                        var raw = Encoding.UTF8.GetBytes(result.ToString(Formatting.None));
                        byte flag;
                        byte[] payload;
                        if (raw.Length > GzipThreshold)
                        {
                            using var ms = new MemoryStream(raw.Length / 2);
                            using (var gz = new GZipStream(ms, CompressionLevel.Fastest, leaveOpen: true))
                                gz.Write(raw, 0, raw.Length);
                            payload = ms.ToArray();
                            flag = 0x01;
                        }
                        else
                        {
                            payload = raw;
                            flag = 0x00;
                        }
                        stream.WriteByte(flag);
                        stream.Write(new byte[]
                        {
                            (byte)(payload.Length >> 24),
                            (byte)(payload.Length >> 16),
                            (byte)(payload.Length >> 8),
                            (byte)payload.Length
                        }, 0, 4);
                        stream.Write(payload, 0, payload.Length);
                        stream.Flush();
                    }
                }
            }
            catch (Exception e)
            {
                if (_running) AIBridgeLogger.Log(LogLevel.WARN, "Server", $"Client error: {e.Message}");
            }
            finally
            {
                AIBridgeLogger.Log(LogLevel.INFO, "Server", $"Client disconnected: {ep}");
            }
        }

        private JObject HandlePing(JObject p)
        {
            // No UI thread hop; this MUST stay sub-millisecond.
            // The MCP server uses ping to verify the connection is alive and the doc is what it expects.
            // scene_version is the etag â€" Claude can short-circuit re-querying if it hasn't changed.
            var doc = RhinoDoc.ActiveDoc;
            var snap = doc != null ? SceneSnapshotRegistry.Get(doc) : null;
            return new JObject
            {
                ["status"] = "ok",
                ["protocol_version"] = PROTOCOL_VERSION,
                ["build_hash"] = BuildHash,
                ["rhino_version"] = RhinoApp.Version?.ToString() ?? "?",
                ["doc_name"] = doc?.Name ?? "Untitled",
                ["doc_serial"] = doc?.RuntimeSerialNumber ?? 0,
                ["unit_system"] = doc?.ModelUnitSystem.ToString() ?? "?",
                ["tolerance"] = doc?.ModelAbsoluteTolerance ?? 0,
                ["scene_version"] = snap?.SceneVersion ?? 0,
                ["object_count"] = snap?.Count ?? 0,
                ["server_time_utc"] = DateTime.UtcNow.ToString("o"),
                ["capabilities"] = new JArray {
                    "deferred_redraw",
                    "lean_response",
                    "scene_cache",
                    "atomic_batch",
                    "reference_resolution",
                    "architect_intelligence",
                    "consolidated_surface",
                    "auto_thumbnail",
                    "gzip_compression",
                    "pbr_materials",
                    "run_command",
                    "set_camera", "dry_run",
                    "viewport_metadata", "query_modes", "design_memory", "scene_sync", "semantic_intelligence",
                },
                ["capabilities_resource"] = "rhino://capabilities",
                ["safe_mode"] = false,
            };
        }

        private static int ReadExact(System.Net.Sockets.NetworkStream s, byte[] buf, int needed)
        {
            int total = 0;
            while (total < needed)
            {
                int n = s.Read(buf, total, needed - total);
                if (n == 0) return total;
                total += n;
            }
            return total;
        }
    }
}
