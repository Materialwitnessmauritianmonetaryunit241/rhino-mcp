// RhinoAIBridge v4.7 -- AIBridgePlugin.cs

using System;
using System.IO;
using Rhino;
using Rhino.PlugIns;

namespace RhinoAIBridge
{
    public class AIBridgePlugin : PlugIn
    {
        public AIBridgePlugin() { Instance = this; }
        public static AIBridgePlugin Instance { get; private set; }

        private static readonly string DiagFile = Path.Combine(
            Path.GetTempPath(), "aibridge_diag.txt");

        private static void Diag(string msg)
        {
            try { File.AppendAllText(DiagFile, $"[{DateTime.Now:HH:mm:ss.fff}] {msg}\n"); } catch { }
        }

        protected override LoadReturnCode OnLoad(ref string errorMessage)
        {
            Diag("OnLoad called -- manual start only (type AIBridge to start)");
            RhinoApp.Closing += OnClosing;
            return LoadReturnCode.Success;
        }

        private void OnClosing(object sender, EventArgs e)
        {
            Diag("OnClosing -- stopping server");
            try { AIBridgeServerController.StopServer(); } catch { }
        }
    }
}
