/**
 * "Mỹ Vị" — Warm, clean, high-contrast everyday Vietnamese kitchen palette.
 * Warm off-white canvas (#FAF8F5), crisp white cards (#FFFFFF), espresso ink (#1C1917),
 * warm terracotta accent (#B53827), and fresh herb green (#23633A).
 */
export type Palette = {
  bg: string;
  surface: string;
  surfaceCard: string;
  surfaceAlt: string;
  text: string;
  muted: string;
  border: string;
  hairline: string;
  borderDashed: string;
  accent: string;
  onAccent: string;
  accentSoft: string;
  accentDisplay: string;
  editorialSurface: string;
  onEditorial: string;
  lime: string;
  limeSurface: string;
  onLime: string;
  storySurface: string;
  onStory: string;
  onStoryMuted: string;
  herb: string;
  herbSoft: string;
  info: string;
  infoSoft: string;
  warn: string;
  warnSoft: string;
  danger: string;
  dangerSoft: string;
  okSoft: string;
  focus: string;
  focusOnEditorial: string;
  tray: string;
  trayGrain: string;
  trayRim: string;
  dish: string;
  glaze: string;
  rice: string;
  shadow: string;
  fresh: { tuoi: string; dung_som: string; dung_ngay: string; kiem_tra: string; chua_ro: string };
  freshSoft: { tuoi: string; dung_som: string; dung_ngay: string; kiem_tra: string; chua_ro: string };
  macro: { kcal: string; protein: string; carb: string; fat: string; fiber: string };
  macroChart: { carb: string; protein: string; lipid: string; fiber: string };
  macroSoft: { fat: string };
  overlay: string;
};

export const light: Palette = {
  bg: '#FAF8F5',
  surface: '#FFFFFF',
  surfaceCard: '#FFFFFF',
  surfaceAlt: '#F3EFE9',
  text: '#1C1917',
  muted: '#57534E',
  border: '#8A8178',
  hairline: '#E7E2DA',
  borderDashed: '#9B9289',
  accent: '#B53827',
  onAccent: '#FFFFFF',
  accentSoft: '#FBECE9',
  accentDisplay: '#8F291B',
  editorialSurface: '#1C1917',
  onEditorial: '#FFFFFF',
  lime: '#23633A',
  limeSurface: '#E6F4EC',
  onLime: '#FFFFFF',
  storySurface: '#1C1917',
  onStory: '#FFFFFF',
  onStoryMuted: '#D6CFC7',
  herb: '#23633A',
  herbSoft: '#E6F4EC',
  info: '#1D4ED8',
  infoSoft: '#EFF6FF',
  warn: '#92400E',
  warnSoft: '#FEF3C7',
  danger: '#B91C1C',
  dangerSoft: '#FEE2E2',
  okSoft: '#E6F4EC',
  focus: '#B53827',
  focusOnEditorial: '#86EFAC',
  tray: '#5A432B',
  trayGrain: '#4A3622',
  trayRim: '#D6CFC7',
  dish: '#FFFFFF',
  glaze: '#1D4ED8',
  rice: '#FFFFFF',
  shadow: 'transparent',
  fresh: { tuoi: '#23633A', dung_som: '#B45309', dung_ngay: '#B91C1C', kiem_tra: '#57534E', chua_ro: '#57534E' },
  freshSoft: { tuoi: '#E6F4EC', dung_som: '#FEF3C7', dung_ngay: '#FEE2E2', kiem_tra: '#F3EFE9', chua_ro: '#F3EFE9' },
  macro: { kcal: '#B53827', protein: '#B53827', carb: '#8F4D00', fat: '#23633A', fiber: '#3D6B0B' },
  macroChart: { carb: '#D97706', protein: '#B53827', lipid: '#23633A', fiber: '#3D6B0B' },
  macroSoft: { fat: '#E6F4EC' },
  overlay: 'rgba(28, 25, 23, 0.48)',
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radius = { sm: 8, md: 12, lg: 16, xl: 20, pill: 9999 } as const;
export const TOUCH = 48;

export const font = {
  displayMedium: 'Newsreader_600SemiBold',
  displaySemibold: 'Newsreader_700Bold',
  regular: 'BeVietnamPro_400Regular',
  medium: 'BeVietnamPro_500Medium',
  semibold: 'BeVietnamPro_600SemiBold',
  bold: 'BeVietnamPro_700Bold',
} as const;

export const size = { xs: 12, sm: 14, md: 16, sub: 18, lg: 20, xl: 24, display: 30, huge: 36 } as const;
