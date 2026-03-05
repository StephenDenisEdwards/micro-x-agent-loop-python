using System.Diagnostics;

namespace WindowsVhs;

class Recorder
{
    readonly List<TapeCommand> _commands;
    readonly RecorderSettings _settings;

    public Recorder(List<TapeCommand> commands)
    {
        _commands = commands;
        _settings = ExtractSettings(commands);
    }

    public async Task RunAsync()
    {
        Console.WriteLine($"Starting recording → {_settings.Output}");
        Console.WriteLine($"Terminal: {_settings.Width}x{_settings.Height}, font {_settings.FontSize}pt");

        // Snapshot windows before launch, then find the new one
        var windowsBefore = Win32.GetAllVisibleWindows();
        var process = LaunchTerminal();
        var hwnd = await WaitForNewWindow(windowsBefore);
        if (hwnd == IntPtr.Zero)
        {
            Console.Error.WriteLine("Error: No new terminal window appeared after 15 seconds.");
            try { process.Kill(); } catch { }
            return;
        }
        Console.Error.WriteLine($"Found new window: 0x{hwnd:X}");

        // Minimize our own console so it can't steal focus
        var ownConsole = Win32.GetConsoleWindow();
        if (ownConsole != IntPtr.Zero)
            Win32.ShowWindow(ownConsole, Win32.SW_MINIMIZE);
        await Task.Delay(300);

        // Position and focus the target terminal
        Win32.ShowWindow(hwnd, Win32.SW_RESTORE);
        Win32.MoveWindow(hwnd, 50, 50, _settings.Width, _settings.Height, true);
        await Task.Delay(500);
        Win32.ForceForeground(hwnd);
        await Task.Delay(500);

        var fg = Win32.GetForegroundWindow();
        Console.Error.WriteLine($"Foreground: 0x{fg:X}, target: 0x{hwnd:X}, match: {fg == hwnd}");
        Console.Error.WriteLine($"Window class: {Win32.GetWindowClassName(hwnd)}");

        // Start capture
        var framesDir = Path.Combine(Path.GetTempPath(), $"wvhs_{Guid.NewGuid():N}");
        using var capture = new ScreenCapture(hwnd, framesDir, _settings.Fps);
        capture.Start();

        Console.WriteLine("Recording...");

        // Execute commands
        foreach (var cmd in _commands)
        {
            switch (cmd)
            {
                case TypeCommand tc:
                    await TypeText(hwnd, tc.Text);
                    break;
                case EnterCommand:
                    Win32.PostKeyPress(hwnd, Win32.VK_RETURN);
                    await Task.Delay(100);
                    break;
                case SleepCommand sc:
                    await Task.Delay(sc.Duration);
                    break;
                case BackspaceCommand bc:
                    for (int i = 0; i < bc.Count; i++)
                    {
                        Win32.PostKeyPress(hwnd, Win32.VK_BACK);
                        await Task.Delay(50);
                    }
                    break;
                case KeyCommand kc:
                    SendNamedKey(hwnd, kc.Key);
                    await Task.Delay(50);
                    break;
                case CtrlCommand cc:
                    Win32.PostCtrlKey(hwnd, cc.Key);
                    await Task.Delay(50);
                    break;
                case HideCommand:
                    capture.Pause();
                    break;
                case ShowCommand:
                    capture.Resume();
                    break;
                case OutputCommand:
                case SetCommand:
                    break; // Already extracted
            }
        }

        // Stop capture
        await capture.StopAsync();
        Console.WriteLine($"Captured {capture.FrameCount} frames");

        if (capture.FrameCount == 0)
        {
            Console.Error.WriteLine("Error: No frames captured.");
            return;
        }

        // Compile GIF
        Console.WriteLine("Compiling GIF...");
        GifCompiler.Compile(framesDir, _settings.Output, _settings.Fps);

        // Cleanup
        try { Directory.Delete(framesDir, true); } catch { }

        // Kill terminal
        try { process.Kill(); } catch { }
    }

    async Task TypeText(IntPtr hwnd, string text)
    {
        foreach (var c in text)
        {
            Win32.PostChar(hwnd, c);
            await Task.Delay(_settings.TypingSpeed);
        }
    }

    static void SendNamedKey(IntPtr hwnd, string key)
    {
        var vk = key switch
        {
            "Up" => Win32.VK_UP,
            "Down" => Win32.VK_DOWN,
            "Left" => Win32.VK_LEFT,
            "Right" => Win32.VK_RIGHT,
            "Tab" => Win32.VK_TAB,
            "Space" => Win32.VK_SPACE,
            "Escape" => Win32.VK_ESCAPE,
            _ => throw new ArgumentException($"Unknown key: {key}")
        };
        Win32.PostKeyPress(hwnd, vk);
    }

    /// <summary>
    /// Finds a new visible window by comparing current windows against a snapshot
    /// taken before launch. Works regardless of whether the terminal is Windows
    /// Terminal, conhost, or any other host.
    /// </summary>
    static async Task<IntPtr> WaitForNewWindow(HashSet<IntPtr> windowsBefore)
    {
        for (int i = 0; i < 30; i++)
        {
            await Task.Delay(500);
            var current = Win32.GetAllVisibleWindows();
            var newWindows = current.Except(windowsBefore).ToList();

            if (newWindows.Count > 0)
            {
                // If multiple new windows appeared, pick the largest (most likely the terminal)
                IntPtr best = IntPtr.Zero;
                int bestArea = 0;
                foreach (var w in newWindows)
                {
                    if (Win32.GetWindowRect(w, out var rect))
                    {
                        var area = rect.Width * rect.Height;
                        if (area > bestArea)
                        {
                            bestArea = area;
                            best = w;
                        }
                    }
                }
                if (best != IntPtr.Zero)
                    return best;
            }
        }

        return IntPtr.Zero;
    }

    Process LaunchTerminal()
    {
        var shell = _settings.Shell;

        // Force conhost.exe to get a legacy console window. Windows Terminal
        // intercepts cmd.exe/powershell launches on Windows 11, and its modern
        // input stack ignores synthetic keystrokes from SendInput. Conhost
        // handles them correctly.
        var shellArgs = shell.Contains("cmd", StringComparison.OrdinalIgnoreCase)
            ? $"\"{shell}\" /k"
            : $"\"{shell}\"";

        var psi = new ProcessStartInfo
        {
            FileName = "conhost.exe",
            Arguments = shellArgs,
            UseShellExecute = true,
            WindowStyle = ProcessWindowStyle.Normal,
        };

        Console.Error.WriteLine($"Launching: conhost.exe {shellArgs}");

        return Process.Start(psi)
            ?? throw new InvalidOperationException($"Failed to start {shell}");
    }

    static RecorderSettings ExtractSettings(List<TapeCommand> commands)
    {
        var settings = new RecorderSettings();

        foreach (var cmd in commands.OfType<OutputCommand>())
            settings.Output = cmd.Filename;

        foreach (var cmd in commands.OfType<SetCommand>())
        {
            switch (cmd.Property)
            {
                case "Width" when int.TryParse(cmd.Value, out var w):
                    settings.Width = w;
                    break;
                case "Height" when int.TryParse(cmd.Value, out var h):
                    settings.Height = h;
                    break;
                case "FontSize" when int.TryParse(cmd.Value, out var fs):
                    settings.FontSize = fs;
                    break;
                case "Fps" when int.TryParse(cmd.Value, out var fps):
                    settings.Fps = fps;
                    break;
                case "TypingSpeed" when int.TryParse(cmd.Value, out var ts):
                    settings.TypingSpeed = ts;
                    break;
                case "Shell":
                    settings.Shell = cmd.Value;
                    break;
                case "Theme":
                    // Theme is cosmetic — user sets terminal theme manually
                    break;
            }
        }

        return settings;
    }
}

class RecorderSettings
{
    public string Output { get; set; } = "output.gif";
    public int Width { get; set; } = 1200;
    public int Height { get; set; } = 600;
    public int FontSize { get; set; } = 16;
    public int Fps { get; set; } = 10;
    public int TypingSpeed { get; set; } = 50; // ms between characters
    public string Shell { get; set; } = "cmd.exe";
}
