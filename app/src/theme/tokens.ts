/**
 * Design tokens, light + dark — "mâm gỗ sơn, bát men lam".
 * Warm rice-paper ground, lacquer red as the single action colour, herb green for freshness / ok,
 * Bát Tràng cobalt only on the crockery drawn on the tray. Freshness colours are always paired with text.
 * Contrast (WCAG 2.2 AA) is checked by scripts/contrast.py against `bg` and `surface`:
 * every text colour ≥ 4.5:1, borders ≥ 3:1.
 */
export type Palette = {
  bg: string;
  surface: string;
  surfaceAlt: string;
  text: string;
  muted: string;
  border: string;
  hairline: string;
  accent: string;
  onAccent: string;
  accentSoft: string;
  herb: string;
  herbSoft: string;
  danger: string;
  dangerSoft: string;
  okSoft: string;
  warnSoft: string;
  tray: string;
  trayGrain: string;
  trayRim: string;
  dish: string;
  glaze: string;
  rice: string;
  shadow: string;
  fresh: { tuoi: string; dung_som: string; dung_ngay: string; kiem_tra: string; chua_ro: string };
  freshSoft: { tuoi: string; dung_som: string; dung_ngay: string; kiem_tra: string; chua_ro: string };
  focus: string;
  overlay: string;
};

export const light: Palette = {
  bg: '#FAF5EB',
  surface: '#FFFCF6',
  surfaceAlt: '#EFE7D8',
  text: '#30251D',
  muted: '#695A4D',
  border: '#8D7D6B',
  hairline: '#E3D8C7',
  accent: '#A63724',
  onAccent: '#FFFFFF',
  accentSoft: '#F8E1D5',
  herb: '#2D6A3E',
  herbSoft: '#DCEBDD',
  danger: '#A63724',
  dangerSoft: '#F8E1D5',
  okSoft: '#DCEBDD',
  warnSoft: '#F7EACB',
  tray: '#7A3322',
  trayGrain: '#8C3D29',
  trayRim: '#C9973D',
  dish: '#FBFAF5',
  glaze: '#2F5597',
  rice: '#FFFFFF',
  shadow: 'rgba(40,30,20,0.10)',
  fresh: { tuoi: '#2D6A3E', dung_som: '#8A5A00', dung_ngay: '#B3261E', kiem_tra: '#5E6660', chua_ro: '#5E6660' },
  freshSoft: { tuoi: '#DCEBDD', dung_som: '#F7EACB', dung_ngay: '#F8DCD7', kiem_tra: '#EFE7D8', chua_ro: '#EFE7D8' },
  focus: '#1D5FA8',
  overlay: 'rgba(20,24,20,0.5)',
};

export const dark: Palette = {
  bg: '#1C1915',
  surface: '#27221C',
  surfaceAlt: '#342D24',
  text: '#F7EFDF',
  muted: '#C7BBAA',
  border: '#958773',
  hairline: '#44392D',
  accent: '#F2948A',
  onAccent: '#2A0E0C',
  accentSoft: '#4A2522',
  herb: '#7CC68C',
  herbSoft: '#21382A',
  danger: '#F2948A',
  dangerSoft: '#4A2522',
  okSoft: '#21382A',
  warnSoft: '#3E3218',
  tray: '#5A2418',
  trayGrain: '#662B1D',
  trayRim: '#B8893A',
  dish: '#E9E6DC',
  glaze: '#3E68B0',
  rice: '#F7F5EE',
  shadow: 'rgba(0,0,0,0.35)',
  fresh: { tuoi: '#7CC68C', dung_som: '#E3B14E', dung_ngay: '#F2948A', kiem_tra: '#C7BBAA', chua_ro: '#C7BBAA' },
  freshSoft: { tuoi: '#21382A', dung_som: '#3E3218', dung_ngay: '#4A2522', kiem_tra: '#342D24', chua_ro: '#342D24' },
  focus: '#8AB8F0',
  overlay: 'rgba(0,0,0,0.65)',
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
/** Radius follows hierarchy: chips/inputs sm, list rows md, hero cards lg. */
export const radius = { sm: 10, md: 14, lg: 22, pill: 999 } as const;
/** Minimum touch target (NFR-A11Y-01: ≥ 44 × 44 dp). */
export const TOUCH = 48;

export const font = {
  regular: 'BeVietnamPro_400Regular',
  medium: 'BeVietnamPro_500Medium',
  semibold: 'BeVietnamPro_600SemiBold',
  bold: 'BeVietnamPro_700Bold',
} as const;

/** Modular scale ≈ 1.2 from 15. */
export const size = { xs: 13, sm: 15, md: 17, lg: 20, xl: 25, xxl: 30, huge: 36 } as const;
