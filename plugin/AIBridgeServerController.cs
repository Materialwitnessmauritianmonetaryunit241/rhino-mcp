// RhinoAIBridge v4.5 — AIBridgeServerController.cs
// by tanishqb | https://github.com/tanishqb/rhino-ai-bridge

using Rhino;

namespace RhinoAIBridge
{
    /// <summary>
    /// Static singleton controller — thin wrapper so plugin/commands don't hold
    /// a direct reference to the AIBridgeServer instance.
    /// </summary>
    public static class AIBridgeServerController
    {
        private static readonly AIBridgeServer _server = new AIBridgeServer();

        public static bool IsRunning => _server.IsRunning;

        public static void StartServer()
        {
            if (!_server.IsRunning)
                _server.Start();
            else
                RhinoApp.WriteLine($"AIBridge: Already running on 127.0.0.1:9544  build:{AIBridgeServer.BuildHash}");
        }

        public static void StopServer()
        {
            if (_server.IsRunning) _server.Stop();
        }
    }
}
