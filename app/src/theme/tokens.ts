/**
 * "Sổ Bếp Thời Báo Mỹ Vị" - Modernized Vietnamese Vintage Broadsheet & Crisp Editorial Nutrition Ledger.
 * Light-only Antique Honey-Parchment Canvas (paper-bg-light.webp / #E3CFA6), Warm Cream Reading Panels (#FAF2E0 / rgba 0.84),
 * Deep Espresso Ink (#19120B >= 12:1 on parchment, >= 16:1 on cream), Brick Red (#9E2F1E), Heritage Banana-Leaf Green (#2E4F33), Sepia Rule (#5A432B / #6E5438).
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
  bg: '#E3CFA6',
  surface: '#FAF2E0',
  surfaceCard: 'rgba(250, 242, 224, 0.84)',
  surfaceAlt: '#EADAB8',
  text: '#19120B',
  muted: '#4E3E2F',
  border: '#5A432B',
  hairline: '#BFA982',
  borderDashed: '#6E5438',
  accent: '#9E2F1E',
  onAccent: '#FAF2E0',
  accentSoft: '#F3E0D4',
  accentDisplay: '#7F2315',
  editorialSurface: '#1A1510',
  onEditorial: '#FAF2E0',
  lime: '#2E4F33',
  limeSurface: '#E2ECE0',
  onLime: '#FAF2E0',
  storySurface: '#1A1510',
  onStory: '#FAF2E0',
  onStoryMuted: '#D8B979',
  herb: '#2E4F33',
  herbSoft: '#E2ECE0',
  info: '#32424A',
  infoSoft: '#ECE6D8',
  warn: '#734609',
  warnSoft: '#F5E7CE',
  danger: '#9E2F1E',
  dangerSoft: '#F5DFD8',
  okSoft: '#E2ECE0',
  focus: '#9E2F1E',
  focusOnEditorial: '#8AB58E',
  tray: '#5A432B',
  trayGrain: '#4A3622',
  trayRim: '#D8B979',
  dish: '#FAF2E0',
  glaze: '#32424A',
  rice: '#FAF2E0',
  shadow: 'transparent',
  fresh: { tuoi: '#2E4F33', dung_som: '#734609', dung_ngay: '#9E2F1E', kiem_tra: '#4E3E2F', chua_ro: '#4E3E2F' },
  freshSoft: { tuoi: '#E2ECE0', dung_som: '#F5E7CE', dung_ngay: '#F5DFD8', kiem_tra: '#EADAB8', chua_ro: '#EADAB8' },
  macro: { kcal: '#9E2F1E', protein: '#9E2F1E', carb: '#734609', fat: '#2E4F33', fiber: '#2E4F33' },
  macroChart: { carb: '#B97A20', protein: '#9E2F1E', lipid: '#2E4F33', fiber: '#5F7D57' },
  macroSoft: { fat: '#E8D9BC' },
  overlay: 'rgba(25,18,11,0.56)',
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radius = { sm: 2, md: 4, lg: 4, xl: 4, pill: 9999 } as const;
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
