# wvhs — Windows VHS Terminal Recorder

A terminal recording tool for Windows that reads VHS-compatible `.tape` scripts and produces GIF output. Built because [VHS](https://github.com/charmbracelet/vhs) doesn't work on Windows (its `ttyd` dependency hangs, and `vhs record` is unsupported).

## How it works

1. Parses a `.tape` script into a sequence of commands
2. Launches a console window via `conhost.exe` (bypasses Windows Terminal, which silently drops synthetic keystrokes)
3. Sends keystrokes to the window via Win32 `PostMessage` (`WM_CHAR`/`WM_KEYDOWN`)
4. Captures screenshots at a configurable framerate in a background thread
5. Compiles the frames into a GIF using ffmpeg (two-pass with palette generation for quality)

## Prerequisites

- .NET 10+ (`dotnet --version` to check)
- ffmpeg on PATH (`scoop install ffmpeg` or `winget install ffmpeg`)

## Build

```bash
cd tools/windows-vhs
dotnet build
```

## Usage

```bash
dotnet run --project tools/windows-vhs -- path/to/script.tape
```

Or after building:

```bash
tools/windows-vhs/bin/Debug/net10.0-windows/wvhs.exe path/to/script.tape
```

## Tape format

Scripts use the same `.tape` format as [VHS](https://github.com/charmbracelet/vhs), with a few Windows-specific additions. Lines starting with `#` are comments.

### Settings

Settings go at the top of the file, before any commands.

| Command | Default | Description |
|---------|---------|-------------|
| `Output <file>` | `output.gif` | Output filename |
| `Set Width <pixels>` | `1200` | Console window width |
| `Set Height <pixels>` | `600` | Console window height |
| `Set FontSize <pt>` | `16` | Cosmetic — set font size in your terminal preferences |
| `Set Fps <n>` | `10` | Screenshot capture framerate |
| `Set TypingSpeed <ms>` | `50` | Delay between keystrokes (lower = faster) |
| `Set Shell <exe>` | `cmd.exe` | Shell to launch inside conhost |
| `Set Theme <name>` | — | Cosmetic — set theme in your terminal preferences |

### Commands

| Command | Description |
|---------|-------------|
| `Type "text"` | Type text character by character with realistic timing |
| `Enter` | Press Enter |
| `Sleep <duration>` | Wait — supports `500ms`, `5s`, `1m` |
| `Backspace [n]` | Press Backspace (default: 1, or specify count) |
| `Up` / `Down` / `Left` / `Right` | Arrow keys |
| `Tab` / `Space` / `Escape` | Special keys |
| `Ctrl+<key>` | Ctrl combination (e.g. `Ctrl+C`) |
| `Hide` | Pause screen capture (frames not recorded) |
| `Show` | Resume screen capture |

### Example

```tape
# Record a demo of the Micro-X agent
Output demo.gif

Set Width 1200
Set Height 600
Set TypingSpeed 25
Set Fps 10

# Start the agent
Type "run.bat --config config-standard-no-summarization-sonnet.json"
Enter
Sleep 10s

# Enter a prompt
Type "Search LinkedIn for senior Python roles in London"
Enter
Sleep 20s
```

## Tips

- **Typing speed:** `50` looks natural. `25` is brisk. `10` is fast. `100` is slow and deliberate.
- **Sleep durations:** These are fixed waits, not "wait until done." You'll need to estimate how long your command takes and adjust after a test run. Re-run the script until the timing feels right.
- **Hide/Show:** Use these to skip boring parts (e.g. a long install step). The tool stops capturing frames during `Hide` and resumes at `Show`, so the GIF jumps cleanly over the gap.
- **Window appearance:** wvhs launches a legacy conhost window, not Windows Terminal. The window will look like a classic console. Set your preferred colours and font size in conhost's properties (right-click the title bar > Properties) before recording.
- **File size:** Higher FPS and longer recordings produce larger GIFs. For a README demo, aim for 10 FPS and under 30 seconds. If the GIF is too large, reduce FPS or trim `Sleep` durations.
- **Re-runs are cheap:** Since the script is just a text file, iterate quickly — adjust timing, re-run, check the GIF, repeat.

## Limitations

- **Windows only** — uses Win32 APIs (`PostMessage`, `GetWindowRect`, `CopyFromScreen`)
- **Legacy console only** — forces `conhost.exe` because Windows Terminal drops synthetic keystrokes
- **No window theming** — `Set Theme` is ignored; configure the console appearance manually before recording
- **Fixed waits** — `Sleep` is a fixed duration, not "wait for output." If your command takes longer than expected, the recording continues without it
- **No audio** — GIF output only
