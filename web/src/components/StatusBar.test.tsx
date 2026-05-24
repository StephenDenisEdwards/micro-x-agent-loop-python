import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusBar } from './StatusBar';

describe('StatusBar', () => {
  it('shows the connection status label', () => {
    render(<StatusBar status="open" model="claude" sessionId="abc" turnInFlight={false} />);
    expect(screen.getByTestId('status-indicator')).toHaveTextContent(/connected/i);
  });

  it('renders cost and tokens when usage is provided', () => {
    render(
      <StatusBar
        status="open"
        model="claude"
        sessionId="abc"
        turnInFlight={false}
        usage={{ input_tokens: 10, output_tokens: 5, cost_usd: 0.0123 }}
      />,
    );
    expect(screen.getByTestId('status-tokens')).toHaveTextContent('10→5');
    expect(screen.getByTestId('status-cost')).toHaveTextContent('$0.0123');
  });

  it('shows a busy indicator while a turn is in flight', () => {
    render(<StatusBar status="open" model="m" sessionId="s" turnInFlight />);
    expect(screen.getByTestId('status-busy')).toBeInTheDocument();
  });

  it('handles connecting / error states', () => {
    const { rerender } = render(<StatusBar status="connecting" model="m" sessionId={null} turnInFlight={false} />);
    expect(screen.getByTestId('status-indicator')).toHaveTextContent(/connecting/);
    rerender(<StatusBar status="error" model="m" sessionId={null} turnInFlight={false} />);
    expect(screen.getByTestId('status-indicator')).toHaveTextContent(/error/);
  });
});
