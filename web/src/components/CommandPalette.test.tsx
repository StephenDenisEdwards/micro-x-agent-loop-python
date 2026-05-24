import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CommandPalette, SLASH_COMMANDS, rankCommands } from './CommandPalette';

function setup(extra: Partial<React.ComponentProps<typeof CommandPalette>> = {}) {
  const props = {
    open: true,
    onClose: vi.fn(),
    onRunSlashCommand: vi.fn(),
    onToggleTasks: vi.fn(),
    onSetTheme: vi.fn(),
    ...extra,
  };
  render(<CommandPalette {...props} />);
  return props;
}

describe('rankCommands', () => {
  it('returns all commands when the query is empty', () => {
    const ranked = rankCommands('', SLASH_COMMANDS);
    expect(ranked.length).toBe(SLASH_COMMANDS.length);
  });

  it('matches by name prefix and ranks prefix matches higher', () => {
    const ranked = rankCommands('/cost', SLASH_COMMANDS);
    expect(ranked[0]!.cmd.name.startsWith('/cost')).toBe(true);
  });

  it('matches against descriptions', () => {
    const ranked = rankCommands('compaction', SLASH_COMMANDS);
    expect(ranked.some((r) => r.cmd.id === 'compact')).toBe(true);
  });
});

describe('CommandPalette', () => {
  it('does not render when closed', () => {
    const props = setup({ open: false });
    expect(screen.queryByTestId('command-palette')).toBeNull();
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it('renders, focuses input, and lists commands', async () => {
    setup();
    expect(screen.getByTestId('command-palette')).toBeInTheDocument();
    const items = screen.getAllByTestId('command-palette-item');
    expect(items.length).toBeGreaterThan(5);
  });

  it('runs the active command on Enter', async () => {
    const props = setup();
    const input = screen.getByTestId('command-palette-input');
    await userEvent.click(input);
    await userEvent.type(input, '/cost');
    await userEvent.keyboard('{Enter}');
    expect(props.onRunSlashCommand).toHaveBeenCalledWith('/cost');
    expect(props.onClose).toHaveBeenCalled();
  });

  it('closes on Escape', async () => {
    const props = setup();
    const input = screen.getByTestId('command-palette-input');
    await userEvent.click(input);
    await userEvent.keyboard('{Escape}');
    expect(props.onClose).toHaveBeenCalled();
  });

  it('invokes onToggleTasks instead of dispatching /tasks', async () => {
    const props = setup();
    const input = screen.getByTestId('command-palette-input');
    await userEvent.click(input);
    await userEvent.type(input, '/tasks');
    await userEvent.keyboard('{Enter}');
    expect(props.onToggleTasks).toHaveBeenCalled();
    expect(props.onRunSlashCommand).not.toHaveBeenCalled();
  });

  it('invokes onSetTheme for theme commands', async () => {
    const props = setup();
    const input = screen.getByTestId('command-palette-input');
    await userEvent.click(input);
    await userEvent.type(input, 'theme: dark');
    await userEvent.keyboard('{Enter}');
    expect(props.onSetTheme).toHaveBeenCalledWith('dark');
  });

  it('arrow keys move the highlight', async () => {
    setup();
    const input = screen.getByTestId('command-palette-input');
    await userEvent.click(input);
    await userEvent.keyboard('{ArrowDown}{ArrowDown}');
    const items = screen.getAllByTestId('command-palette-item');
    expect(items[2]!).toHaveClass('active');
  });

  it('shows an empty state when no matches', async () => {
    setup();
    await userEvent.type(screen.getByTestId('command-palette-input'), 'zzzzz-no-match');
    expect(screen.getByTestId('command-palette-empty')).toBeInTheDocument();
  });
});
