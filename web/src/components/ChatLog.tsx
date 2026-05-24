import { useEffect, useRef } from 'react';
import type { ChatMessage } from '../types/protocol';

interface ChatLogProps {
  messages: ChatMessage[];
  banner?: string;
}

export function ChatLog({ messages, banner }: ChatLogProps): React.JSX.Element {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Pin to bottom when new messages arrive.
    el.scrollTop = el.scrollHeight;
  }, [messages]);

  return (
    <div className="chat-log" ref={ref} data-testid="chat-log" role="log" aria-live="polite">
      {banner ? <pre className="banner" data-testid="chat-banner">{banner}</pre> : null}
      {messages.map((m) => (
        <div
          key={m.id}
          className={`message ${m.role}${m.pending ? ' pending' : ''}`}
          data-role={m.role}
          data-message-id={m.id}
        >
          {m.text}
        </div>
      ))}
    </div>
  );
}
