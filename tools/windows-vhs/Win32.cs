using System.Runtime.InteropServices;

namespace WindowsVhs;

static class Win32
{
    // --- DPI awareness ---

    [DllImport("shcore.dll")]
    public static extern int SetProcessDpiAwareness(int value);

    public const int PROCESS_PER_MONITOR_DPI_AWARE = 2;

    // --- Window management ---

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int x, int y, int width, int height, bool repaint);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    public const int SW_MINIMIZE = 6;
    public const int SW_RESTORE = 9;

    [DllImport("kernel32.dll")]
    public static extern IntPtr GetConsoleWindow();

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left, Top, Right, Bottom;
        public int Width => Right - Left;
        public int Height => Bottom - Top;
    }

    // --- Keyboard input ---

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT
    {
        public uint Type;
        public INPUTUNION U;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct INPUTUNION
    {
        [FieldOffset(0)] public KEYBDINPUT Ki;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT
    {
        public ushort Vk;
        public ushort Scan;
        public uint Flags;
        public uint Time;
        public IntPtr ExtraInfo;
    }

    public const uint INPUT_KEYBOARD = 1;
    public const uint KEYEVENTF_KEYUP = 0x0002;
    public const uint KEYEVENTF_UNICODE = 0x0004;

    // Virtual key codes
    public const ushort VK_RETURN = 0x0D;
    public const ushort VK_BACK = 0x08;
    public const ushort VK_TAB = 0x09;
    public const ushort VK_ESCAPE = 0x1B;
    public const ushort VK_SPACE = 0x20;
    public const ushort VK_UP = 0x26;
    public const ushort VK_DOWN = 0x28;
    public const ushort VK_LEFT = 0x25;
    public const ushort VK_RIGHT = 0x27;
    public const ushort VK_CONTROL = 0xA2;

    // --- Window messages ---

    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr FindWindowEx(IntPtr hWndParent, IntPtr hWndChildAfter, string? lpszClass, string? lpszWindow);

    [DllImport("user32.dll")]
    public static extern int GetClassName(IntPtr hWnd, System.Text.StringBuilder lpClassName, int nMaxCount);

    public const uint WM_CHAR = 0x0102;
    public const uint WM_KEYDOWN = 0x0100;
    public const uint WM_KEYUP = 0x0101;

    /// <summary>
    /// Sends a character to a window via WM_CHAR message. Works even when
    /// the target window doesn't respond to SendInput (e.g. Windows Terminal).
    /// </summary>
    public static void PostChar(IntPtr hWnd, char c)
    {
        PostMessage(hWnd, WM_CHAR, (IntPtr)c, IntPtr.Zero);
    }

    /// <summary>
    /// Sends a virtual key press via WM_KEYDOWN + WM_KEYUP messages.
    /// </summary>
    public static void PostKeyPress(IntPtr hWnd, ushort vk)
    {
        PostMessage(hWnd, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero);
        PostMessage(hWnd, WM_KEYUP, (IntPtr)vk, IntPtr.Zero);
    }

    /// <summary>
    /// Sends Ctrl+key via messages.
    /// </summary>
    public static void PostCtrlKey(IntPtr hWnd, char key)
    {
        // For Ctrl+C etc, send WM_KEYDOWN with the control key modifier
        // encoded in the virtual key code
        var vk = (ushort)char.ToUpper(key);
        PostMessage(hWnd, WM_KEYDOWN, (IntPtr)VK_CONTROL, IntPtr.Zero);
        PostMessage(hWnd, WM_KEYDOWN, (IntPtr)vk, IntPtr.Zero);
        PostMessage(hWnd, WM_KEYUP, (IntPtr)vk, IntPtr.Zero);
        PostMessage(hWnd, WM_KEYUP, (IntPtr)VK_CONTROL, IntPtr.Zero);
    }

    /// <summary>
    /// Get the class name of a window to help identify the right target.
    /// </summary>
    public static string GetWindowClassName(IntPtr hWnd)
    {
        var sb = new System.Text.StringBuilder(256);
        GetClassName(hWnd, sb, sb.Capacity);
        return sb.ToString();
    }

    // --- Helpers ---

    public static void SendKeyPress(ushort vk)
    {
        var inputs = new INPUT[2];
        inputs[0] = MakeKeyInput(vk, 0);
        inputs[1] = MakeKeyInput(vk, KEYEVENTF_KEYUP);
        SendInput(2, inputs, Marshal.SizeOf<INPUT>());
    }

    public static void SendUnicodeChar(char c)
    {
        var inputs = new INPUT[2];
        inputs[0] = MakeUnicodeInput(c, 0);
        inputs[1] = MakeUnicodeInput(c, KEYEVENTF_KEYUP);
        SendInput(2, inputs, Marshal.SizeOf<INPUT>());
    }

    public static void SendCtrlKey(char key)
    {
        var vk = (ushort)char.ToUpper(key);
        var inputs = new INPUT[4];
        inputs[0] = MakeKeyInput(VK_CONTROL, 0);
        inputs[1] = MakeKeyInput(vk, 0);
        inputs[2] = MakeKeyInput(vk, KEYEVENTF_KEYUP);
        inputs[3] = MakeKeyInput(VK_CONTROL, KEYEVENTF_KEYUP);
        SendInput(4, inputs, Marshal.SizeOf<INPUT>());
    }

    // --- Focus (bypasses foreground lock) ---

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr lpdwProcessId);

    [DllImport("kernel32.dll")]
    public static extern uint GetCurrentThreadId();

    [DllImport("user32.dll")]
    public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);

    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr hWnd);

    /// <summary>
    /// Forces a window to the foreground by attaching to the current foreground
    /// window's thread input queue first. This bypasses the Windows restriction
    /// that only the foreground process can call SetForegroundWindow.
    /// </summary>
    public static void ForceForeground(IntPtr hWnd)
    {
        var foreground = GetForegroundWindow();
        var foregroundThread = GetWindowThreadProcessId(foreground, IntPtr.Zero);
        var currentThread = GetCurrentThreadId();

        if (foregroundThread != currentThread)
        {
            AttachThreadInput(currentThread, foregroundThread, true);
            SetForegroundWindow(hWnd);
            BringWindowToTop(hWnd);
            AttachThreadInput(currentThread, foregroundThread, false);
        }
        else
        {
            SetForegroundWindow(hWnd);
            BringWindowToTop(hWnd);
        }
    }

    // --- Window enumeration (fallback for Windows Terminal) ---

    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    public static IntPtr FindWindowByPid(int pid)
    {
        IntPtr found = IntPtr.Zero;
        EnumWindows((hWnd, _) =>
        {
            GetWindowThreadProcessId(hWnd, out var windowPid);
            if (windowPid == (uint)pid && IsWindowVisible(hWnd))
            {
                found = hWnd;
                return false; // stop enumerating
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    /// <summary>
    /// Returns all currently visible top-level window handles.
    /// </summary>
    public static HashSet<IntPtr> GetAllVisibleWindows()
    {
        var windows = new HashSet<IntPtr>();
        EnumWindows((hWnd, _) =>
        {
            if (IsWindowVisible(hWnd))
                windows.Add(hWnd);
            return true;
        }, IntPtr.Zero);
        return windows;
    }

    static INPUT MakeKeyInput(ushort vk, uint flags) => new()
    {
        Type = INPUT_KEYBOARD,
        U = new INPUTUNION
        {
            Ki = new KEYBDINPUT { Vk = vk, Flags = flags }
        }
    };

    static INPUT MakeUnicodeInput(char c, uint flags) => new()
    {
        Type = INPUT_KEYBOARD,
        U = new INPUTUNION
        {
            Ki = new KEYBDINPUT { Scan = c, Flags = KEYEVENTF_UNICODE | flags }
        }
    };
}
