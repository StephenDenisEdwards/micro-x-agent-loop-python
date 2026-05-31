import { useState } from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ErrorBoundary } from './ErrorBoundary';

function Boom({ message = 'kaboom' }: { message?: string }): React.JSX.Element {
  throw new Error(message);
}

function Toggleable(): React.JSX.Element {
  const [explode, setExplode] = useState(false);
  if (explode) throw new Error('toggled');
  return (
    <button data-testid="trigger" onClick={() => setExplode(true)}>
      go
    </button>
  );
}

describe('ErrorBoundary', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // React logs caught errors to console.error in dev — silence to keep test output clean.
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <div data-testid="ok">all good</div>
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('ok')).toBeInTheDocument();
    expect(screen.queryByTestId('error-boundary')).toBeNull();
  });

  it('renders fallback UI with the error message when a child throws', () => {
    render(
      <ErrorBoundary>
        <Boom message="something specific" />
      </ErrorBoundary>,
    );
    const card = screen.getByTestId('error-boundary');
    expect(card).toHaveTextContent('Something broke');
    expect(card).toHaveTextContent('something specific');
  });

  it('calls the custom fallback when provided', () => {
    render(
      <ErrorBoundary fallback={(err) => <div data-testid="custom">caught: {err.message}</div>}>
        <Boom message="nope" />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('custom')).toHaveTextContent('caught: nope');
  });

  it('resets to children when Dismiss is clicked', async () => {
    const user = userEvent.setup();
    render(
      <ErrorBoundary>
        <Toggleable />
      </ErrorBoundary>,
    );
    await user.click(screen.getByTestId('trigger'));
    expect(screen.getByTestId('error-boundary')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /dismiss/i }));
    // After reset the boundary re-renders children; Toggleable starts fresh.
    expect(screen.queryByTestId('error-boundary')).toBeNull();
    expect(screen.getByTestId('trigger')).toBeInTheDocument();
  });
});
