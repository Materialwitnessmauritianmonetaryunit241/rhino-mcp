using System;
using System.Collections.Concurrent;
using System.Threading;
using Newtonsoft.Json.Linq;
using Rhino;

namespace RhinoAIBridge
{
    /// <summary>
    /// UI-thread dispatcher.
    /// 
    /// v3 used per-call ManualResetEventSlim allocation:
    ///     var wait = new ManualResetEventSlim(false);
    ///     RhinoApp.InvokeOnUiThread(() => { ...; wait.Set(); });
    ///     wait.Wait(...);
    /// 
    /// v4 keeps RhinoApp.InvokeOnUiThread (still the only safe primitive Rhino exposes for cross-thread doc access),
    /// but pools the wait handles via ThreadLocal. Each TCP client thread reuses the same handle for every command.
    /// 
    /// This isn't the biggest win in Phase 1, but it eliminates per-call allocations on the hot path
    /// and sets us up cleanly for Phase 4 (request multiplexing) where we'll want a persistent worker queue.
    /// </summary>
    public static class UiDispatcher
    {
        // One reusable wait handle per calling thread. Cheap, cleared between calls.
        private static readonly ThreadLocal<WorkSlot> _slot = new ThreadLocal<WorkSlot>(() => new WorkSlot(), trackAllValues: false);

        private sealed class WorkSlot
        {
            public readonly ManualResetEventSlim Wait = new ManualResetEventSlim(false);
            public JObject Result;
            public Exception Error;

            public void Reset()
            {
                Wait.Reset();
                Result = null;
                Error = null;
            }
        }

        public static void Start() { /* nothing to start; the UI thread is Rhino's */ }
        public static void Stop()
        {
            // Dispose any tracked thread-local handles. ThreadLocal will clean up on plugin unload.
        }

        /// <summary>
        /// Run <paramref name="func"/> on Rhino's UI thread. Blocks the calling thread (a TCP client thread)
        /// until completion or timeout.
        /// </summary>
        public static JObject Invoke(Func<JObject> func, TimeSpan timeout)
        {
            var slot = _slot.Value;
            slot.Reset();

            RhinoApp.InvokeOnUiThread(new Action(() =>
            {
                try { slot.Result = func(); }
                catch (Exception e) { slot.Error = e; }
                finally { slot.Wait.Set(); }
            }));

            if (!slot.Wait.Wait(timeout))
                throw new TimeoutException($"Command timed out ({timeout.TotalSeconds}s)");

            if (slot.Error != null) throw slot.Error;
            return slot.Result ?? new JObject { ["status"] = "error", ["message"] = "No result" };
        }
    }
}
