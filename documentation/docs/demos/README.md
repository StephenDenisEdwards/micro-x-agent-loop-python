# Demo Recordings

Terminal demo recordings using [VHS](https://github.com/charmbracelet/vhs) by Charmbracelet.

## Prerequisites

Install VHS and ffmpeg:

```bash
scoop install vhs ffmpeg
```

## Running

From the project root:

```bash
vhs documentation/docs/demos/demo.tape
```

This generates `demo.gif` in the current directory.

## Scripts

| Script | Description |
|--------|-------------|
| [demo.tape](demo.tape) | Main demo — starts the agent, enters a prompt, selects an execution mode |

## Editing

VHS scripts are plain text. Key commands:

- `Type "text"` — types text with realistic keystroke timing
- `Enter` — presses Enter
- `Sleep 5s` — waits (adjust to match actual agent response times)
- `Set Width/Height/FontSize/Theme` — configure the terminal appearance

After editing, re-run `vhs <script>.tape` to regenerate the GIF.

See the [VHS documentation](https://github.com/charmbracelet/vhs#vhs) for the full command reference.
