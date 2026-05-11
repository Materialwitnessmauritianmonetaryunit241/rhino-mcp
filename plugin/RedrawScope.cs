// RhinoAIBridge v4.5 — RedrawScope.cs
// by tanishqb | https://github.com/tanishqb/rhino-ai-bridge

using System;
using System.Threading;
using Rhino;

namespace RhinoAIBridge
{
    /// <summary>
    /// Defers viewport redraws across nested operations.
    /// 
    /// The v3 plugin called Doc.Views.Redraw() at the end of every single create/transform/etc.
    /// For an architect's typical "build a 4-story office" turn (50+ ops in a batch),
    /// that's 50 full viewport redraws blocking the UI thread — easily several seconds wasted.
    /// 
    /// Pattern:
    ///   using (RedrawScope.Defer())
    ///   {
    ///       // many AddBrep / Transform / Delete calls
    ///       RedrawScope.Mark();   // tell the scope "something changed"
    ///   }   // exactly ONE redraw fires here, only if Mark() was called
    /// 
    /// Scopes nest. Only the outermost scope actually redraws.
    /// Thread-safe via a single counter on the UI thread (all dispatched commands run there).
    /// </summary>
    public sealed class RedrawScope : IDisposable
    {
        private static int _depth;        // nesting depth
        private static bool _dirty;       // any mutation since outermost scope opened?
        private bool _disposed;

        private RedrawScope() { _depth++; }

        public static RedrawScope Defer() => new RedrawScope();

        /// <summary>Mark the scene as needing a redraw. Cheap. Call after any mutation.</summary>
        public static void Mark()
        {
            if (_depth > 0) { _dirty = true; return; }
            // No active scope → redraw immediately (legacy / direct-call path).
            try { RhinoDoc.ActiveDoc?.Views?.Redraw(); } catch { }
        }

        /// <summary>True if we're currently inside any deferred-redraw scope.</summary>
        public static bool IsActive => _depth > 0;

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            _depth--;
            if (_depth > 0) return;     // inner scope, outer still holds

            // Outermost scope ending — flush exactly one redraw if anything was marked.
            if (_dirty)
            {
                _dirty = false;
                try { RhinoDoc.ActiveDoc?.Views?.Redraw(); } catch { }
            }
        }
    }
}
