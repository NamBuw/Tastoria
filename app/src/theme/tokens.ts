/**
 * Design tokens, light + dark (spec v2 §9, v1 §5.2).
 * Rice-cream background, terracotta accent, freshness green / amber / orange-red / grey.
 * Contrast checked against `bg` and `surface` (WCAG 2.2 AA, ≥ 4.5:1 for text, ≥ 3:1 for borders):
 * light text 13.9, muted 6.3, accent 5.0, onAccent/accent 5.7, freshness ≥ 4.5;
 * dark text 15.0, muted 8.9, accent 7.3, onAccent/accent 7.3, freshness ≥ 5.8.
 */
export type Palette = {
  bg: string;
  surface: string;
  surfaceAlt: string;
  text: string;
  muted: string;
  border: string;
  accent: string;
  onAccent: string;
  accentSoft: string;
  danger: string;
  dangerSoft: string;
  okSoft: string;
  tray: string;
  trayRim: string;
  dish: string;
  rice: string;
  fresh: { tuoi: string; dung_som: string; dung_ngay: string; kiem_tra: string; chua_ro: string };
  focus: string;
  overlay: string;
};

export const light: Palette = {
  bg: '#F6F0E2',
  surface: '#FFFBF2',
  surfaceAlt: '#EFE6D3',
  text: '#2A2118',
  muted: '#62564A',
  border: '#8A7B6A',
  accent: '#A84B26',
  onAccent: '#FFFFFF',
  accentSoft: '#F2DCCB',
  danger: '#A8321A',
  dangerSoft: '#F8DDD5',
  okSoft: '#DCEBD5',
  tray: '#D9B98F',
  trayRim: '#B98F5E',
  dish: '#FFFBF2',
  rice: '#FFFFFF',
  fresh: { tuoi: '#2C7A30', dung_som: '#946000', dung_ngay: '#C0391B', kiem_tra: '#6E6A64', chua_ro: '#6E6A64' },
  focus: '#1D5FA8',
  overlay: 'rgba(30,22,14,0.45)',
};

export const dark: Palette = {
  bg: '#1A1612',
  surface: '#26201A',
  surfaceAlt: '#322A22',
  text: '#F2EADB',
  muted: '#C2B5A3',
  border: '#8C7D6C',
  accent: '#E3916A',
  onAccent: '#1A1612',
  accentSoft: '#4A3124',
  danger: '#F07A5A',
  dangerSoft: '#4A2620',
  okSoft: '#24381F',
  tray: '#5A4430',
  trayRim: '#7A5E42',
  dish: '#2E2620',
  rice: '#3A3129',
  fresh: { tuoi: '#6CC070', dung_som: '#E0A63A', dung_ngay: '#F07A5A', kiem_tra: '#A8A39C', chua_ro: '#A8A39C' },
  focus: '#8AB8F0',
  overlay: 'rgba(0,0,0,0.6)',
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radius = { sm: 8, md: 12, lg: 20, pill: 999 } as const;
/** Minimum touch target (NFR-A11Y-01: ≥ 44 × 44 dp). */
export const TOUCH = 48;

export const font = {
  regular: 'BeVietnamPro_400Regular',
  medium: 'BeVietnamPro_500Medium',
  semibold: 'BeVietnamPro_600SemiBold',
  bold: 'BeVietnamPro_700Bold',
} as const;

export const size = { xs: 13, sm: 15, md: 17, lg: 20, xl: 24, xxl: 30, huge: 34 } as const;
