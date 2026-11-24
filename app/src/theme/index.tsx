import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react';
import { Platform } from 'react-native';

import { light, type Palette } from './tokens';

export * from './layout';
export * from './tokens';

type Theme = {
  c: Palette;
  scheme: 'light';
};

const ThemeCtx = createContext<Theme>({
  c: light,
  scheme: 'light',
});

/** Locked unconditionally to the Light "Sổ Bếp Mỹ Vị" vintage newsprint palette. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const scheme = 'light' as const;
  const c = light;

  useEffect(() => {
    if (Platform.OS !== 'web' || typeof document === 'undefined') return;
    document.documentElement.dataset.theme = 'light';
    document.documentElement.style.colorScheme = 'light';
    if (document.body) {
      document.body.style.backgroundColor = c.bg;
      document.body.style.fontFamily = 'BeVietnamPro_400Regular, "Be Vietnam Pro", system-ui, sans-serif';
    }
    let meta = document.querySelector('meta[name="theme-color"]') as HTMLMetaElement | null;
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'theme-color';
      document.head.appendChild(meta);
    }
    meta.content = c.bg;
  }, [c.bg]);

  const value = useMemo<Theme>(() => ({ c, scheme }), [c]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export function useTheme(): Theme {
  return useContext(ThemeCtx);
}
