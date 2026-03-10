# Markdown Rendering — Manual Test Plan

Step-by-step walkthrough of the progressive markdown rendering feature. Run these from the project root directory.

> **Prerequisites**
> - Python 3.11+ with the agent installed (`pip install -e .`)
> - `rich>=13.0.0` installed (included in dependencies)
> - A working `config.json` with at least one LLM provider
> - `.env` with valid API keys

---

## 1. Markdown Rendering Enabled (Default)

The default configuration has `MarkdownRenderingEnabled: true`. All tests in this section use the default.

### Test 1.1: Code block with syntax highlighting

```
you> Write a Python hello world program
```

**Expected:**
- Thinking spinner appears while waiting for LLM response
- Response streams progressively (no flicker, smooth redraws)
- Code block renders with syntax highlighting (coloured keywords, strings, etc.)
- Code block has a visible border/background distinguishing it from prose

### Test 1.2: Bold, italic, and lists

```
you> Give me 3 tips for writing clean code. Use bold for the tip name and italic for the explanation.
```

**Expected:**
- Bold text renders as **bold** (bright/highlighted, not raw `**` markers)
- Italic text renders as *italic* (not raw `*` markers)
- Bulleted or numbered list is properly indented and formatted

### Test 1.3: Markdown table

```
you> Show me a comparison table of Python, JavaScript, and Rust with columns for typing, speed, and use case.
```

**Expected:**
- Table renders with aligned columns and visible borders
- No raw `|` pipe characters visible as plain text

### Test 1.4: Mixed content (prose + code + list)

```
you> Explain the factory design pattern with a Python example and list 3 benefits.
```

**Expected:**
- Prose renders as normal text
- Code block renders with syntax highlighting
- List renders with proper indentation
- All three content types flow naturally with appropriate spacing

### Test 1.5: Streaming feels smooth

```
you> Write a detailed explanation of how HTTP works, at least 5 paragraphs.
```

**Expected:**
- Text appears progressively as tokens arrive
- No visible flicker or screen jumping during streaming
- The response builds up smoothly, rerendering the markdown as each token arrives
- Final output is a clean, fully rendered markdown document

### Test 1.6: Spinner during tool execution

```
you> What files are in the current directory?
```

(Requires a filesystem MCP tool to be configured)

**Expected:**
- Thinking spinner appears initially
- Spinner changes to "Running filesystem__list_files..." (or similar) during tool execution
- After tool completes, markdown-rendered response streams in
- Spinner and markdown don't overlap or produce visual artefacts

### Test 1.7: Multiple tool calls in one turn

```
you> Read the contents of pyproject.toml and tell me what dependencies are listed.
```

**Expected:**
- Spinner shows for each tool call
- Text segments between tool calls each render correctly as markdown
- No visual artefacts at the transitions between spinner and text

### Test 1.8: Error display

Trigger an error by referencing a non-existent tool or causing a known failure.

**Expected:**
- Error message displays clearly with `[Error: ...]` formatting
- Error does not corrupt the terminal state
- Next prompt (`you>`) appears correctly

---

## 2. Markdown Rendering Disabled

To test plain-text mode, create a config file or modify your existing one:

```json
{
  "MarkdownRenderingEnabled": false
}
```

### Test 2.1: Plain text output

```
you> Write a Python hello world program
```

**Expected:**
- Response streams token by token via raw `print()` (original behaviour)
- No markdown rendering — raw `**bold**` and `` ``` `` markers visible
- Thinking spinner uses the original `\r`-based ASCII animation (not rich)

### Test 2.2: Spinner in plain mode

```
you> What files are in the current directory?
```

**Expected:**
- Thread-based ASCII spinner appears (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`)
- Spinner label shows tool name
- Same behaviour as before the markdown feature was added

---

## 3. WebSocket CLI Client

Connect to a running API server to verify the WebSocket CLI client inherits markdown rendering.

```bash
# Terminal 1: Start the server
python -m micro_x_agent_loop --server start

# Terminal 2: Connect as client
python -m micro_x_agent_loop --server http://localhost:8321
```

### Test 3.1: Markdown rendering over WebSocket

```
you> Write a Python hello world program
```

**Expected:**
- Same markdown rendering as direct REPL (code blocks, bold, etc.)
- Spinner appears during thinking and tool execution
- Streaming is smooth with no flicker

---

## 4. Edge Cases

### Test 4.1: Empty response

Trigger a scenario where the LLM returns an empty or very short response.

```
you> Reply with just "ok"
```

**Expected:**
- "ok" renders cleanly without artefacts
- No leftover spinner or blank rendered blocks

### Test 4.2: Very long response

```
you> List all HTTP status codes with their meanings.
```

**Expected:**
- Long response streams without performance degradation
- Terminal scrolling works correctly
- Final rendered output is complete and readable

### Test 4.3: Interrupted response (ESC key, Windows only)

Start a long response and press ESC to cancel.

**Expected:**
- Response stops cleanly
- `[Interrupted]` message appears
- Terminal state is clean — next `you>` prompt works correctly
- No orphaned spinner or partial Live region

### Test 4.4: ask_user during markdown mode

If the LLM calls `ask_user`, the markdown renderer should stop cleanly before showing the questionary prompt.

**Expected:**
- Any accumulated markdown is finalized (printed) before the question
- Questionary prompt appears and works correctly
- After answering, the response continues with markdown rendering

---

## 5. Configuration Verification

### Test 5.1: Default config enables markdown

Start the agent without any `MarkdownRenderingEnabled` setting in config.

**Expected:** Markdown rendering is active (code blocks are highlighted, bold renders, etc.)

### Test 5.2: Explicit disable

Add `"MarkdownRenderingEnabled": false` to config.

**Expected:** Plain text mode — raw markdown syntax visible, ASCII spinner used.

### Test 5.3: Explicit enable

Add `"MarkdownRenderingEnabled": true` to config.

**Expected:** Same as Test 5.1.
