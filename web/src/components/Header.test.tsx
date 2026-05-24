import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Header } from './Header';
import { KeyHints } from './KeyHints';

describe('Header', () => {
  it('renders title and optional subtitle', () => {
    render(<Header title="MICRO-X" subtitle="claude" />);
    expect(screen.getByTestId('app-header')).toHaveTextContent('MICRO-X');
    expect(screen.getByTestId('app-subtitle')).toHaveTextContent('claude');
  });

  it('omits subtitle when not provided', () => {
    render(<Header title="MICRO-X" />);
    expect(screen.queryByTestId('app-subtitle')).toBeNull();
  });
});

describe('KeyHints', () => {
  it('renders the default key hints', () => {
    render(<KeyHints />);
    const el = screen.getByTestId('keyhints');
    expect(el).toHaveTextContent('Ctrl+P');
    expect(el).toHaveTextContent('Commands');
  });

  it('renders custom hints when provided', () => {
    render(<KeyHints hints={[{ key: 'Alt+X', label: 'custom' }]} />);
    expect(screen.getByTestId('keyhints')).toHaveTextContent('Alt+X');
    expect(screen.getByTestId('keyhints')).toHaveTextContent('custom');
  });
});
