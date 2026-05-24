import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ToolPanel, formatDuration, formatSize, summariseArgs } from './ToolPanel';
import type { ToolEntry } from '../types/protocol';

describe('ToolPanel helpers', () => {
  it('summariseArgs picks the configured keys for known tools', () => {
    expect(summariseArgs('filesystem__read_file', { path: '/a.txt' })).toBe('path=/a.txt');
    expect(summariseArgs('filesystem__grep', { pattern: 'foo', path: '/x' })).toBe(
      'pattern=foo  path=/x',
    );
  });

  it('summariseArgs falls back to the first non-empty key', () => {
    expect(summariseArgs('unknown_tool', { a: '', b: 'value' })).toBe('b=value');
  });

  it('summariseArgs returns empty string for null/undefined input', () => {
    expect(summariseArgs('whatever', null)).toBe('');
    expect(summariseArgs('whatever', undefined)).toBe('');
  });

  it('formatDuration handles ms and seconds', () => {
    expect(formatDuration(0)).toBe('');
    expect(formatDuration(undefined)).toBe('');
    expect(formatDuration(250)).toBe('250ms');
    expect(formatDuration(2500)).toBe('2.5s');
  });

  it('formatSize handles chars, KB, MB', () => {
    expect(formatSize(undefined)).toBe('');
    expect(formatSize(0)).toBe('');
    expect(formatSize(123)).toBe('123 chars');
    expect(formatSize(4096)).toBe('4 KB');
    expect(formatSize(2 * 1024 * 1024)).toBe('2.0 MB');
  });
});

describe('ToolPanel component', () => {
  it('shows the empty state when no tools have run', () => {
    render(<ToolPanel tools={[]} />);
    expect(screen.getByTestId('tool-empty')).toBeInTheDocument();
  });

  it('renders running tools and their args', () => {
    const tools: ToolEntry[] = [
      {
        toolUseId: 't1',
        name: 'filesystem__read_file',
        status: 'running',
        input: { path: '/etc/hosts' },
        startedAt: 0,
      },
    ];
    render(<ToolPanel tools={tools} />);
    const entry = screen.getByTestId('tool-entry');
    expect(entry.dataset.status).toBe('running');
    expect(entry).toHaveTextContent('filesystem__read_file');
    expect(entry).toHaveTextContent('path=/etc/hosts');
  });

  it('shows ok and error states with badges and size info', () => {
    const tools: ToolEntry[] = [
      {
        toolUseId: 't1',
        name: 'a',
        status: 'ok',
        startedAt: 0,
        durationMs: 1000,
        resultChars: 5000,
        wasSummarized: true,
        wasTruncated: false,
      },
      {
        toolUseId: 't2',
        name: 'b',
        status: 'error',
        startedAt: 0,
        durationMs: 200,
      },
    ];
    render(<ToolPanel tools={tools} />);
    const [ok, err] = screen.getAllByTestId('tool-entry');
    expect(ok!.dataset.status).toBe('ok');
    expect(ok).toHaveTextContent('4 KB');
    expect(ok).toHaveTextContent('summ');
    expect(err!.dataset.status).toBe('error');
  });

  it('hides itself when the hidden prop is set', () => {
    render(<ToolPanel tools={[]} hidden />);
    expect(screen.getByTestId('tool-panel')).toHaveClass('hidden');
  });
});
