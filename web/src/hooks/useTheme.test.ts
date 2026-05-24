import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useTheme } from './useTheme';

beforeEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  window.localStorage.clear();
});

describe('useTheme', () => {
  it('defaults to dark when nothing is stored', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('reads the stored theme on mount', () => {
    window.localStorage.setItem('micro-x-theme', 'nord');
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('nord');
  });

  it('setTheme updates the document and localStorage', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme('dracula'));
    expect(result.current.theme).toBe('dracula');
    expect(document.documentElement.dataset.theme).toBe('dracula');
    expect(window.localStorage.getItem('micro-x-theme')).toBe('dracula');
  });

  it('toggle flips between dark and light', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(result.current.theme).toBe('light');
    act(() => result.current.toggle());
    expect(result.current.theme).toBe('dark');
  });
});
