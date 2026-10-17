import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useColorScheme } from 'react-native';

import { dark, light, type Palette } from './tokens';

export * from './tokens';

type Theme = { c: Palette; scheme: 'light' | 'dark' };

const ThemeCtx = createContext<Theme>({ c: light, scheme: 'light' });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const scheme = useColorScheme() === 'dark' ? 'dark' : 'light';
  const value = useMemo<Theme>(() => ({ c: scheme === 'dark' ? dark : light, scheme }), [scheme]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export function useTheme(): Theme {
  return useContext(ThemeCtx);
}
