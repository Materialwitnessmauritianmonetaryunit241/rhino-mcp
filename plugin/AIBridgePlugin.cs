// RhinoAIBridge v4.5 — AIBridgePlugin.cs
// by tanishqb | https://github.com/tanishqb/rhino-ai-bridge

using System;
using Rhino;
using Rhino.PlugIns;

namespace RhinoAIBridge
{
    public class AIBridgePlugin : PlugIn
    {
        public AIBridgePlugin() { Instance = this; }
        public static AIBridgePlugin Instance { get; private set; }

        protected override LoadReturnCode OnLoad(ref string errorMessage)
        {
            // Defer server start until Rhino's UI is fully idle.
            // Starting in OnLoad is too early — the doc may not exist yet.
            RhinoApp.Idle += OnIdle;
            RhinoApp.Closing += OnClosing;
            return LoadReturnCode.Success;
        }

        private bool _started = false;
        private void OnIdle(object sender, EventArgs e)
        {
            if (_started) return;
            _started = true;
            RhinoApp.Idle -= OnIdle;
            try { AIBridgeServerController.StartServer(); }
            catch (Exception ex) { RhinoApp.WriteLine($"AIBridge: auto-start failed — {ex.Message}"); }
        }

        private void OnClosing(object sender, EventArgs e)
        {
            try { AIBridgeServerController.StopServer(); } catch { }
        }
    }
}
