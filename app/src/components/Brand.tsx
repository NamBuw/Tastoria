import { Image } from 'expo-image';
import { type ReactNode } from 'react';
import { View, type StyleProp, type ViewStyle } from 'react-native';
import Svg, { Circle, G, Path } from 'react-native-svg';

import { font, radius, size as typeSize, space, useTheme } from '@/theme';

import { T } from './ui';

export const SLOGAN = 'Cơm nhà mỗi ngày';

/**
 * Clean warm-kitchen canvas background with high text contrast and zero visual noise.
 */
export function PaperBackground({
  children,
  style,
  testID,
}: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}) {
  const { c } = useTheme();
  return (
    <View testID={testID} style={[{ flex: 1, backgroundColor: c.bg }, style]}>
      {children}
    </View>
  );
}

export const FOOD_PHOTOS = {
  table: require('../../assets/food/vietnamese-table.webp'),
  bunDau: require('../../assets/food/bun-dau.webp'),
  freshBowl: require('../../assets/food/fresh-bowl.webp'),
  pho: require('../../assets/food/pho.webp'),
  caramelPork: require('../../assets/food/caramel-pork.webp'),
  caramelTrout: require('../../assets/food/caramel-trout.webp'),
  tofuGreens: require('../../assets/food/tofu-greens.webp'),
  seabassGinger: require('../../assets/food/seabass-ginger.webp'),
  omelette: require('../../assets/food/omelette.webp'),
  tomatoEgg: require('../../assets/food/tomato-egg.webp'),
  morningGlory: require('../../assets/food/morning-glory.webp'),
  cabbageShrimp: require('../../assets/food/cabbage-shrimp.webp'),
  silkenTofu: require('../../assets/food/silken-tofu.webp'),
  bunThitNuong: require('../../assets/food/bun-thit-nuong.webp'),
  beefPho: require('../../assets/food/beef-pho.webp'),
} as const;

export type FoodPhotoSource = (typeof FOOD_PHOTOS)[keyof typeof FOOD_PHOTOS];

function normDish(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .trim();
}

/**
 * Returns a local Vietnamese dish photograph ONLY when it genuinely matches the dish
 * (never substituting unrelated dish photos like water spinach on pumpkin or eggplant dishes).
 */
export function recipePhotoFor(
  nameOrSlug?: string | null,
  _slot?: 'man' | 'rau' | 'canh' | 'trang_mieng' | string | null,
): FoodPhotoSource | null {
  const n = normDish(nameOrSlug ?? '');
  if (!n) return null;

  if (!n.includes('canh') && n.includes('trung') && (n.includes('ca chua') || n.includes('sot ca'))) {
    return FOOD_PHOTOS.tomatoEgg;
  }
  if (n.includes('trung chien') || n.includes('trung ran') || n.includes('trung duc') || n.includes('omelette')) {
    return FOOD_PHOTOS.omelette;
  }
  if (n.includes('thit kho') || n.includes('thit rang') || n.includes('suon kho') || n.includes('suon rim') || n.includes('ba chi')) {
    return FOOD_PHOTOS.caramelPork;
  }
  if (n.includes('bun thit nuong') || n.includes('thit nuong')) return FOOD_PHOTOS.bunThitNuong;
  if (n.includes('bun dau')) return FOOD_PHOTOS.bunDau;
  if (n.includes('com tam')) return FOOD_PHOTOS.table;
  if (n.includes('dau phu non') || n.includes('dau hu non')) return FOOD_PHOTOS.silkenTofu;
  if (!n.includes('canh') && (n.includes('dau phu') || n.includes('dau hu'))) {
    return FOOD_PHOTOS.tofuGreens;
  }
  const isPlantCa = /\bca (tim|rot|chua|phao|ri|phe)\b/.test(n);
  if (!n.includes('canh') && !isPlantCa && /\bca\b.*\b(kho|rim|sot)\b/.test(n)) {
    return FOOD_PHOTOS.caramelTrout;
  }
  if (!n.includes('canh') && !isPlantCa && /\bca\b.*\b(hap|gung|chien|ran|nuong)\b/.test(n)) {
    return FOOD_PHOTOS.seabassGinger;
  }
  if (!n.includes('canh') && n.includes('rau muong')) {
    return FOOD_PHOTOS.morningGlory;
  }
  if (!n.includes('canh') && !n.includes('goi') && (n.includes('cai thao') || (n.includes('tom') && n.includes('xao')))) {
    return FOOD_PHOTOS.cabbageShrimp;
  }
  if (n.includes('pho bo')) return FOOD_PHOTOS.beefPho;
  if (n.includes('pho') || n.includes('hu tieu') || n.includes('bun')) return FOOD_PHOTOS.pho;
  if (n.includes('canh') || n.includes('sup')) {
    if (n.includes('tom') || n.includes('cai')) return FOOD_PHOTOS.cabbageShrimp;
    return FOOD_PHOTOS.freshBowl;
  }
  if (/\b(thit|ga|vit|bo|heo|lon)\b/.test(n) && !n.includes('ca tim') && !n.includes('bi')) {
    return FOOD_PHOTOS.caramelPork;
  }
  return null;
}

/**
 * Framed vintage broadsheet crest ("Mỹ Vị"): dark espresso square
 * with double gold-cream inner border and Newsreader Bold mark.
 */
export function BroadsheetCrest({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const { c } = useTheme();
  const box = size === 'sm' ? 38 : size === 'lg' ? 52 : 44;
  const fontSize = size === 'sm' ? 14 : size === 'lg' ? 17 : 15;
  const lineHeight = size === 'sm' ? 16 : size === 'lg' ? 19 : 17;
  return (
    <View
      style={{
        width: box,
        height: box,
        backgroundColor: c.editorialSurface,
        borderWidth: 1,
        borderColor: c.border,
        borderRadius: radius.sm,
        padding: 3,
      }}>
      <View
        style={{
          flex: 1,
          borderWidth: 1.5,
          borderColor: c.trayRim,
          borderRadius: 1,
          padding: 1.5,
        }}>
        <View
          style={{
            flex: 1,
            borderWidth: 1,
            borderColor: c.borderDashed,
            alignItems: 'center',
            justifyContent: 'center',
          }}>
          <T
            style={{
              fontFamily: font.displaySemibold,
              fontSize,
              lineHeight,
              letterSpacing: -0.3,
              color: c.trayRim,
              textAlign: 'center',
            }}>
            {size === 'sm' ? 'MV' : 'Mỹ\nVị'}
          </T>
        </View>
      </View>
    </View>
  );
}

/** Crisp broadsheet wordmark aligned with "Sổ Bếp Mỹ Vị" (Crest + Newsreader Bold + Brick Red ink). */
export function Wordmark({
  size = 'md',
  subtitle,
  masthead = false,
}: {
  size?: 'sm' | 'md' | 'lg';
  subtitle?: string;
  masthead?: boolean;
}) {
  const { c } = useTheme();
  const fontSize = size === 'sm' ? typeSize.sub : size === 'lg' ? typeSize.display : typeSize.xl;
  const lineHeight = size === 'sm' ? 24 : size === 'lg' ? 34 : 28;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm, flexShrink: 1 }}>
      {masthead ? <BroadsheetCrest size={size === 'lg' ? 'lg' : 'md'} /> : null}
      <View style={{ flexShrink: 1, gap: 2 }}>
        {masthead ? (
          <T
            style={{
              fontFamily: font.bold,
              fontSize: 10,
              lineHeight: 14,
              letterSpacing: 1.1,
              color: c.muted,
            }}>
            SỔ BẾP
          </T>
        ) : null}
        <T
          accessibilityRole="header"
          style={{
            fontFamily: font.displaySemibold,
            fontSize,
            lineHeight,
            letterSpacing: -0.5,
            color: c.accent,
          }}>
          Mỹ Vị
        </T>
        {subtitle ? (
          masthead ? (
            <View
              style={{
                backgroundColor: c.border,
                paddingHorizontal: space.sm,
                paddingVertical: 2,
                borderRadius: radius.sm,
                alignSelf: 'flex-start',
                marginTop: 1,
              }}>
              <T v="small" style={{ color: c.surface, fontFamily: font.medium, fontSize: 11, lineHeight: 15 }} numberOfLines={1}>
                {subtitle}
              </T>
            </View>
          ) : (
            <T v="small" tone="muted" numberOfLines={1}>
              {subtitle}
            </T>
          )
        ) : null}
      </View>
    </View>
  );
}

export function BrandHeader({ subtitle }: { subtitle?: string }) {
  return (
    <View style={{ marginTop: 4 }}>
      <Wordmark size="lg" masthead subtitle={subtitle ?? SLOGAN} />
    </View>
  );
}

/**
 * Compact square vermilion seal stamp ("triện đỏ", BẾP VIỆT).
 * Double-bordered vermilion frame with high-contrast vermilion ink on warm paper.
 */
export function VermilionSeal({ label = 'BẾP VIỆT' }: { label?: string }) {
  const { c } = useTheme();
  return (
    <View
      style={{
        alignSelf: 'flex-start',
        borderWidth: 1.5,
        borderColor: c.accent,
        borderRadius: radius.sm,
        backgroundColor: c.surface,
        padding: 2,
      }}>
      <View
        style={{
          borderWidth: 1,
          borderColor: c.accentSoft,
          paddingHorizontal: 6,
          paddingVertical: 2,
          backgroundColor: c.accentSoft,
        }}>
        <T
          style={{
            fontFamily: font.bold,
            fontSize: 10,
            lineHeight: 13,
            letterSpacing: 0.9,
            color: c.accent,
          }}>
          {label}
        </T>
      </View>
    </View>
  );
}

/** Pure-SVG 8-petal Vietnamese star anise ("hoa hồi") culinary emblem. */
export function StarAniseMark({ size: s = 16, color }: { size?: number; color?: string }) {
  const { c } = useTheme();
  const strokeColor = color ?? c.border;
  const cx = 12;
  const cy = 12;
  return (
    <Svg width={s} height={s} viewBox="0 0 24 24" accessibilityElementsHidden importantForAccessibility="no">
      <G stroke={strokeColor} strokeWidth={1.35} fill="none" strokeLinecap="round" strokeLinejoin="round">
        {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => (
          <Path
            key={deg}
            d="M12 10.2 C10.6 7.4 10.8 4.4 12 2.6 C13.2 4.4 13.4 7.4 12 10.2 Z"
            rotation={deg}
            origin={`${cx}, ${cy}`}
          />
        ))}
      </G>
      <Circle cx={cx} cy={cy} r={1.8} fill={c.accent} />
    </Svg>
  );
}

function DividerRuleSide({ borderColor, hairlineColor }: { borderColor: string; hairlineColor: string }) {
  return (
    <View style={{ flex: 1, gap: 2, justifyContent: 'center' }}>
      <View style={{ height: 1, backgroundColor: borderColor }} />
      <View style={{ height: 1, backgroundColor: hairlineColor }} />
    </View>
  );
}

function DividerFretTick({ color }: { color: string }) {
  return (
    <Svg width={12} height={10} viewBox="0 0 12 10" accessibilityElementsHidden importantForAccessibility="no">
      <Path d="M1 2h9v6H5V5h2" stroke={color} strokeWidth={1.1} fill="none" strokeLinecap="square" />
    </Svg>
  );
}

/**
 * Pure-SVG Vietnamese "hoa hồi" (star anise) + "hồi văn" hairline double-rule divider.
 */
export function StarAniseDivider({ label }: { label?: string }) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.sm }}>
      <DividerFretTick color={c.border} />
      <DividerRuleSide borderColor={c.border} hairlineColor={c.hairline} />
      <StarAniseMark size={15} />
      {label ? (
        <T v="small" style={{ color: c.herb, fontFamily: font.semibold, flexShrink: 1, textAlign: 'center' }}>
          {label}
        </T>
      ) : null}
      <DividerRuleSide borderColor={c.border} hairlineColor={c.hairline} />
      <DividerFretTick color={c.border} />
    </View>
  );
}

/** Subtle open-margin banana-leaf & rice-stalk botanical line-art (never behind text). */
export function BotanicalCornerMark() {
  const { c } = useTheme();
  return (
    <View
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no"
      style={{ position: 'absolute', right: 10, bottom: 8, opacity: 0.14 }}>
      <Svg width={68} height={54} viewBox="0 0 68 54">
        <Path
          d="M8 46 C22 36 38 22 60 8 M16 41 C22 28 32 20 44 16 M26 34 C34 33 44 29 53 22 M36 26 C40 18 48 13 57 10"
          stroke={c.herb}
          strokeWidth={1.4}
          fill="none"
          strokeLinecap="round"
        />
        <Path
          d="M16 41 C12 31 18 20 30 14 C41 9 52 8 60 8 C58 18 52 28 42 35 C31 43 21 45 16 41 Z"
          stroke={c.border}
          strokeWidth={1.1}
          fill="none"
        />
      </Svg>
    </View>
  );
}

export function BrandHeroPhoto({ height = 200 }: { height?: number }) {
  const { c } = useTheme();
  return (
    <Image
      source={FOOD_PHOTOS.table}
      contentFit="cover"
      accessibilityLabel="Mâm cơm gia đình Việt Nam nhiều món dọn sẵn trên bàn ăn"
      style={{ width: '100%', height, backgroundColor: c.surfaceAlt }}
    />
  );
}
