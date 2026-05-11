using Rhino;
using Rhino.Commands;

namespace RhinoAIBridge.Commands
{
    public class AIBridgeCommand : Command
    {
        public static AIBridgeCommand Instance { get; private set; }
        public AIBridgeCommand() { Instance = this; }
        public override string EnglishName => "AIBridge";
        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            AIBridgeServerController.StartServer();
            return Result.Success;
        }
    }

    public class AIBridgeStopCommand : Command
    {
        public static AIBridgeStopCommand Instance { get; private set; }
        public AIBridgeStopCommand() { Instance = this; }
        public override string EnglishName => "AIBridgeStop";
        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            AIBridgeServerController.StopServer();
            return Result.Success;
        }
    }
}
