import { useRef, useState, type KeyboardEvent } from 'react';

interface PromptInputProps {
  disabled?: boolean;
  placeholder?: string;
  onSubmit: (text: string) => void;
}

/**
 * Mirrors PromptTextArea in src/micro_x_agent_loop/tui/app.py:
 *   - Enter submits.
 *   - Shift+Enter / Ctrl+Enter / Ctrl+J inserts a newline.
 */
export function PromptInput({
  disabled,
  placeholder,
  onSubmit,
}: PromptInputProps): React.JSX.Element {
  const [value, setValue] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>): void {
    if (e.key !== 'Enter') return;
    if (e.shiftKey || e.ctrlKey || e.metaKey) {
      // Allow newline — default behaviour.
      return;
    }
    e.preventDefault();
    submit();
  }

  function submit(): void {
    const text = value.trim();
    if (!text) return;
    setValue('');
    onSubmit(text);
    // Refocus after submit.
    requestAnimationFrame(() => ref.current?.focus());
  }

  return (
    <div className="input-row" data-testid="prompt-row">
      <textarea
        ref={ref}
        value={value}
        disabled={disabled}
        placeholder={placeholder ?? 'Type a message — Enter to send, Shift+Enter for newline'}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        rows={2}
        data-testid="prompt-input"
        aria-label="Prompt input"
      />
      <button
        className="primary"
        disabled={disabled || !value.trim()}
        onClick={submit}
        data-testid="send-button"
        aria-label="Send"
      >
        Send
      </button>
    </div>
  );
}
