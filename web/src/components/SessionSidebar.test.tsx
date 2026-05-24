import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SessionSidebar } from './SessionSidebar';

describe('SessionSidebar', () => {
  it('renders an empty state when there are no sessions', () => {
    render(<SessionSidebar sessions={[]} activeId={null} onSelect={() => {}} onNew={() => {}} />);
    expect(screen.getByText(/no sessions yet/i)).toBeInTheDocument();
  });

  it('marks the active session and fires onSelect on click', async () => {
    const onSelect = vi.fn();
    render(
      <SessionSidebar
        sessions={[
          { id: 'a', title: 'Alpha' },
          { id: 'b', title: 'Beta' },
        ]}
        activeId="a"
        onSelect={onSelect}
        onNew={() => {}}
      />,
    );
    const items = screen.getAllByTestId('session-item');
    expect(items[0]!).toHaveClass('active');
    expect(items[1]!).not.toHaveClass('active');
    await userEvent.click(items[1]!);
    expect(onSelect).toHaveBeenCalledWith('b');
  });

  it('fires onNew when the New button is clicked', async () => {
    const onNew = vi.fn();
    render(<SessionSidebar sessions={[]} activeId={null} onSelect={() => {}} onNew={onNew} />);
    await userEvent.click(screen.getByTestId('new-session-button'));
    expect(onNew).toHaveBeenCalled();
  });

  it('hides itself when hidden prop is set', () => {
    render(<SessionSidebar sessions={[]} activeId={null} onSelect={() => {}} onNew={() => {}} hidden />);
    expect(screen.getByTestId('session-sidebar')).toHaveClass('hidden');
  });

  it('supports keyboard activation', async () => {
    const onSelect = vi.fn();
    render(
      <SessionSidebar
        sessions={[{ id: 'a', title: 'Alpha' }]}
        activeId={null}
        onSelect={onSelect}
        onNew={() => {}}
      />,
    );
    const item = screen.getByTestId('session-item');
    item.focus();
    await userEvent.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith('a');
  });
});
