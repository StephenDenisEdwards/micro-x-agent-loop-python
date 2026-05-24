import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import type { PendingQuestion } from '../types/protocol';

interface AskUserModalProps {
  question: PendingQuestion;
  onAnswer: (answer: string) => void;
  onCancel: () => void;
}

export function AskUserModal({
  question,
  onAnswer,
  onCancel,
}: AskUserModalProps): React.JSX.Element {
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, [question.id]);

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>): void {
    if (e.key === 'Enter') {
      e.preventDefault();
      const trimmed = text.trim();
      if (trimmed) onAnswer(trimmed);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onCancel();
    }
  }

  return (
    <div className="modal-backdrop" data-testid="ask-user-modal" role="dialog" aria-modal>
      <div className="modal">
        <h2>Question from agent</h2>
        <div data-testid="ask-user-question">{question.text}</div>
        {question.options && question.options.length > 0 ? (
          <div className="modal-options">
            {question.options.map((opt) => (
              <button
                key={opt.value}
                onClick={() => onAnswer(opt.value)}
                data-testid="ask-user-option"
                data-option-value={opt.value}
              >
                {opt.label || opt.value}
              </button>
            ))}
          </div>
        ) : (
          <input
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Your answer…"
            data-testid="ask-user-input"
            aria-label="Answer"
          />
        )}
        <div className="modal-actions">
          <button onClick={onCancel} data-testid="ask-user-cancel">Cancel</button>
          {(!question.options || question.options.length === 0) && (
            <button
              className="primary"
              onClick={() => {
                const trimmed = text.trim();
                if (trimmed) onAnswer(trimmed);
              }}
              disabled={!text.trim()}
              data-testid="ask-user-submit"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
