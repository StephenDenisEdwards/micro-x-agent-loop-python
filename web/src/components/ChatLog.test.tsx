import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { ChatLog } from './ChatLog';

describe('ChatLog', () => {
  it('renders nothing but the banner when there are no messages', () => {
    render(<ChatLog messages={[]} banner="banner-text" />);
    expect(screen.getByTestId('chat-banner')).toHaveTextContent('banner-text');
    expect(screen.queryAllByRole('log')[0]!.querySelectorAll('.message').length).toBe(0);
  });

  it('renders user / assistant / system / error messages with role classes', () => {
    render(
      <ChatLog
        messages={[
          { id: 'a', role: 'user', text: 'hi' },
          { id: 'b', role: 'assistant', text: 'hello', pending: true },
          { id: 'c', role: 'system', text: 'note' },
          { id: 'd', role: 'error', text: 'boom' },
        ]}
      />,
    );
    const log = screen.getByTestId('chat-log');
    const user = within(log).getByText('hi');
    expect(user).toHaveClass('user');
    const assistant = within(log).getByText('hello');
    expect(assistant).toHaveClass('assistant');
    expect(assistant).toHaveClass('pending');
    expect(within(log).getByText('note')).toHaveClass('system');
    expect(within(log).getByText('boom')).toHaveClass('error');
  });
});
