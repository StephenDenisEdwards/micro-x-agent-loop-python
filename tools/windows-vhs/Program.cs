using WindowsVhs;

// DPI awareness for accurate screen capture
Win32.SetProcessDpiAwareness(Win32.PROCESS_PER_MONITOR_DPI_AWARE);

if (args.Length == 0)
{
    Console.WriteLine("wvhs - Windows VHS terminal recorder");
    Console.WriteLine();
    Console.WriteLine("Usage: wvhs <script.tape>");
    Console.WriteLine();
    Console.WriteLine("Tape commands:");
    Console.WriteLine("  Output <file.gif>       Output filename");
    Console.WriteLine("  Set Width <pixels>      Terminal width (default: 1200)");
    Console.WriteLine("  Set Height <pixels>     Terminal height (default: 600)");
    Console.WriteLine("  Set FontSize <pt>       Font size (cosmetic — set in terminal)");
    Console.WriteLine("  Set Fps <n>             Capture framerate (default: 10)");
    Console.WriteLine("  Set TypingSpeed <ms>    Delay between keystrokes (default: 50)");
    Console.WriteLine("  Set Shell <exe>         Shell to launch (default: cmd.exe)");
    Console.WriteLine("  Type \"text\"             Type text with realistic timing");
    Console.WriteLine("  Enter                   Press Enter");
    Console.WriteLine("  Sleep <duration>        Wait (e.g., 5s, 500ms, 1m)");
    Console.WriteLine("  Backspace [n]           Press Backspace (default: 1)");
    Console.WriteLine("  Up/Down/Left/Right      Arrow keys");
    Console.WriteLine("  Tab/Space/Escape        Special keys");
    Console.WriteLine("  Ctrl+<key>              Ctrl combination (e.g., Ctrl+C)");
    Console.WriteLine("  Hide                    Pause capture");
    Console.WriteLine("  Show                    Resume capture");
    Console.WriteLine("  # comment               Comments are ignored");
    return;
}

var tapePath = args[0];
if (!File.Exists(tapePath))
{
    Console.Error.WriteLine($"Error: File not found: {tapePath}");
    return;
}

try
{
    var commands = TapeParser.Parse(tapePath);
    Console.WriteLine($"Parsed {commands.Count} commands from {tapePath}");

    var recorder = new Recorder(commands);
    await recorder.RunAsync();
}
catch (FormatException ex)
{
    Console.Error.WriteLine($"Parse error: {ex.Message}");
}
catch (Exception ex)
{
    Console.Error.WriteLine($"Error: {ex.Message}");
}
