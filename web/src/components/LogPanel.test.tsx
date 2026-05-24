import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LogPanel } from './LogPanel';

describe('LogPanel', () => {
  it('renders empty state when no lines', () => {
    render(<LogPanel lines={[]} />);
    expect(screen.getByText(/No log lines/i)).toBeInTheDocument();
  });

  it('renders each log line', () => {
    render(
      <LogPanel
        lines={[
          { id: '1', text: 'line one', ts: 1 },
          { id: '2', text: 'line two', ts: 2 },
        ]}
      />,
    );
    const lines = screen.getAllByTestId('log-line');
    expect(lines).toHaveLength(2);
    expect(lines[0]!).toHaveTextContent('line one');
  });

  it('hides itself when hidden prop is set', () => {
    render(<LogPanel lines={[]} hidden />);
    expect(screen.getByTestId('log-panel')).toHaveClass('hidden');
  });
});
