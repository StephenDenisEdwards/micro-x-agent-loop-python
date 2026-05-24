import { useCallback, useEffect, useState } from 'react';

export const THEMES = [
  'dark',
  'light',
  'nord',
  'gruvbox',
  'dracula',
  'tokyo-night',
  'monokai',
  'solarized-light',
] as const;

export type ThemeName = (typeof THEMES)[number];

const STORAGE_KEY = 'micro-x-theme';

function readStoredTheme(): ThemeName {
  if (typeof window === 'undefined') return 'dark';
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v && (THEMES as readonly string[]).includes(v)) return v as ThemeName;
  } catch {
    /* localStorage may be blocked */
  }
  return 'dark';
}

export function useTheme(): { theme: ThemeName; setTheme: (t: ThemeName) => void; toggle: () => void } {
  const [theme, setThemeState] = useState<ThemeName>(() => readStoredTheme());

  useEffect(() => {
    if (typeof document === 'undefined') return;
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  const setTheme = useCallback((t: ThemeName) => setThemeState(t), []);
  const toggle = useCallback(
    () => setThemeState((t) => (t === 'dark' ? 'light' : 'dark')),
    [],
  );

  return { theme, setTheme, toggle };
}
