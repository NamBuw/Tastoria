import { Image } from 'expo-image';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import type { Schemas } from '@/api/client';
import { font, radius, space, TOUCH, useTheme } from '@/theme';

import { recipePhotoFor } from './Brand';
import { T } from './ui';

// ---- freshness ----------------------------------------------------------------------------------

export type Freshness = 'tuoi' | 'dung_som' | 'dung_ngay' | 'kiem_tra' | 'chua_ro';

export const FRESH_LABEL: Record<Freshness, string> = {
  tuoi: 'tươi',
  dung_som: 'nên dùng sớm',
  dung_ngay: 'dùng ngay',
  kiem_tra: 'kiểm tra trước khi dùng',
  chua_ro: 'chưa rõ độ tươi',
};

/** Accessible status badge combining indicator and plain text (WCAG 1.4.1). */
export function FreshBadge({
  value,
  small,
  testID = 'fresh-badge',
}: {
  value: Freshness;
  small?: boolean;
  testID?: string;
}) {
  const { c } = useTheme();
  const color = c.fresh[value];
  return (
    <View
      testID={testID}
      style={[
        styles.badge,
        {
          backgroundColor: c.freshSoft[value],
          paddingHorizontal: small ? 8 : 10,
          paddingVertical: small ? 3 : 4,
        },
      ]}
      accessibilityLabel={`Độ tươi: ${FRESH_LABEL[value]}`}>
      <View
        style={[
          styles.dot,
          value === 'kiem_tra' || value === 'chua_ro'
            ? { borderWidth: 1.5, borderColor: color, backgroundColor: 'transparent' }
            : { backgroundColor: color },
        ]}
      />
      <Text style={{ fontFamily: font.semibold, fontSize: small ? 12 : 14, lineHeight: small ? 16 : 20, color, flexShrink: 1 }}>
        {FRESH_LABEL[value]}
      </Text>
    </View>
  );
}

// ---- grams --------------------------------------------------------------------------------------

export function fmtG(min: number, max: number): string {
  const r = (x: number) => (x >= 100 ? Math.round(x / 10) * 10 : Math.round(x));
  const a = r(min);
  const b = r(max);
  if (a === b) return `${a} g`;
  return `${a} đến ${b} g`;
}

export const SLOT_LABEL: Record<'man' | 'rau' | 'canh', string> = { man: 'Mặn', rau: 'Rau', canh: 'Canh' };

// ---- tray ---------------------------------------------------------------------------------------

type TrayItem = Pick<Schemas['MealPlanItem'], 'id' | 'slot' | 'recipe_name_vi'>;

/**
 * Editorial 3-dish meal tray (mâm cơm): interactive tactile slots paired with
 * verified food photography when available and clean slot typography otherwise.
 */
export function Tray({
  items,
  bowls,
  size: S = 320,
  onPressItem,
  compact,
}: {
  items: TrayItem[];
  bowls?: number | null;
  size?: number;
  onPressItem?: (it: TrayItem) => void;
  compact?: boolean;
}) {
  const { c } = useTheme();
  const order = { man: 0, rau: 1, canh: 2 } as const;
  const sorted = [...items].sort((a, b) => order[a.slot] - order[b.slot]);

  return (
    <View
      style={{
        width: '100%',
        maxWidth: Math.max(S, 320),
        alignSelf: 'center',
        borderRadius: radius.lg,
        borderWidth: 1.5,
        borderColor: c.border,
        backgroundColor: c.surfaceAlt,
        overflow: 'hidden',
      }}
      accessibilityLabel={`Mâm: ${sorted.map((i) => `${SLOT_LABEL[i.slot]} ${i.recipe_name_vi}`).join(', ')}${bowls ? `, cơm ${fmtBowls(bowls)} bát` : ''}`}>
      <View
        style={{
          flexDirection: 'row',
          justifyContent: 'space-between',
          alignItems: 'center',
          paddingHorizontal: compact ? space.md : space.lg,
          paddingVertical: space.sm,
          borderBottomWidth: 1,
          borderBottomColor: c.hairline,
          backgroundColor: c.surface,
        }}>
        <T v="label">Mâm cơm {sorted.length} món</T>
        <T v="small" tone="muted" tabular>
          {bowls ? `Cơm ${fmtBowls(bowls)} bát / người` : 'Cơm trắng ăn kèm'}
        </T>
      </View>

      {sorted.map((it, idx) => {
        const photo = recipePhotoFor(it.recipe_name_vi, it.slot);
        const content = (
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: space.md,
              paddingHorizontal: compact ? space.md : space.lg,
              paddingVertical: compact ? space.sm : space.md,
              borderTopWidth: idx > 0 ? 1 : 0,
              borderTopColor: c.hairline,
              minHeight: TOUCH,
            }}>
            {photo ? (
              <Image
                source={photo}
                contentFit="cover"
                style={{ width: compact ? 44 : 52, height: compact ? 44 : 52, borderRadius: radius.sm, backgroundColor: c.surface }}
                accessibilityLabel={it.recipe_name_vi}
              />
            ) : (
              <View
                style={{
                  width: compact ? 44 : 52,
                  height: compact ? 44 : 52,
                  borderRadius: radius.sm,
                  backgroundColor: c.accentSoft,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                <T v="small" tone="accent" style={{ fontFamily: font.semibold }}>
                  {SLOT_LABEL[it.slot]}
                </T>
              </View>
            )}
            <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
              <T v="small" tone="accent" style={{ fontFamily: font.semibold }}>
                Món {SLOT_LABEL[it.slot].toLowerCase()}
              </T>
              <T v={compact ? 'body' : 'title'} numberOfLines={2}>
                {it.recipe_name_vi}
              </T>
            </View>
            {onPressItem ? <Icon name="chevron-right" size={18} color={c.muted} /> : null}
          </View>
        );

        return onPressItem ? (
          <Pressable
            key={it.id}
            testID={`tray-dish-${it.slot}`}
            accessibilityRole="button"
            accessibilityLabel={`${SLOT_LABEL[it.slot]}: ${it.recipe_name_vi}. Chạm để xem, đổi món hoặc xem thiếu gì`}
            onPress={() => onPressItem(it)}
            style={({ pressed }) => ({
              backgroundColor: pressed ? c.surface : 'transparent',
              transform: [{ scale: pressed ? 0.99 : 1 }],
            })}>
            {content}
          </Pressable>
        ) : (
          <View key={it.id}>{content}</View>
        );
      })}
    </View>
  );
}

export function fmtBowls(b: number): string {
  return String(b).replace('.', ',');
}

// ---- kcal range bar -----------------------------------------------------------------------------

/** Calorie range per person against the target (BR-NUT-06); "đang hiệu chỉnh" when the range is not calibrated. */
export function KcalBar({
  low,
  high,
  target,
}: {
  low: number | null;
  high: number | null;
  target: number | null;
}) {
  const { c } = useTheme();
  if (low == null || high == null) {
    return (
      <View style={{ gap: 4 }}>
        <T v="label">Calo mỗi người</T>
        <T tone="muted">Khoảng calo đang hiệu chỉnh (chưa đủ dữ liệu đối chiếu).</T>
      </View>
    );
  }
  const max = Math.max(high, target ?? 0) * 1.25;
  const pct = (x: number) => `${Math.min(100, (x / max) * 100)}%` as const;
  const status =
    target == null ? null : high < target * 0.9 ? 'thấp hơn mục tiêu' : low > target * 1.1 ? 'cao hơn mục tiêu' : 'trong mục tiêu';
  return (
    <View style={{ gap: 6 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: space.sm }}>
        <T v="label">Calo mỗi người (xấp xỉ)</T>
        <T v="label" tabular testID="kcal-value">
          {Math.round(low)} đến {Math.round(high)} kcal
        </T>
      </View>
      <View
        style={{ height: 8, borderRadius: radius.sm, backgroundColor: c.surfaceAlt, overflow: 'hidden' }}
        accessibilityLabel={`Khoảng ${Math.round(low)} đến ${Math.round(high)} kcal mỗi người${
          target ? `, mục tiêu bữa ${Math.round(target)} kcal` : ''
        }`}>
        <View
          style={{
            position: 'absolute',
            left: pct(low),
            width: `${Math.max(2, ((high - low) / max) * 100)}%`,
            top: 0,
            bottom: 0,
            backgroundColor: c.accent,
            borderRadius: radius.sm,
          }}
        />
        {target ? (
          <View style={{ position: 'absolute', left: pct(target), top: -2, bottom: -2, width: 2.5, backgroundColor: c.text }} />
        ) : null}
      </View>
      <T v="small" tone="muted">
        {target
          ? `Vạch dọc: mục tiêu bữa ${Math.round(target)} kcal, ${status}`
          : 'Chưa có mục tiêu năng lượng. Đặt trong Cài đặt › Hồ sơ.'}
      </T>
    </View>
  );
}

// ---- icons (clean monoline stroke paths: 24x24 viewBox, strokeWidth 1.8) -----------------------

export type IconName =
  | 'home'
  | 'box'
  | 'tray'
  | 'cart'
  | 'book'
  | 'gear'
  | 'camera'
  | 'bag'
  | 'clock'
  | 'check'
  | 'close'
  | 'plus'
  | 'minus'
  | 'arrow-right'
  | 'arrow-left'
  | 'arrow-up-right'
  | 'chevron-left'
  | 'chevron-right'
  | 'compass'
  | 'shield'
  | 'sliders'
  | 'search'
  | 'trash'
  | 'edit'
  | 'eye'
  | 'eye-off'
  | 'flame'
  | 'menu'
  | 'alert-triangle';

export function Icon({ name, color, size: s = 24 }: { name: IconName; color: string; size?: number }) {
  const p = { stroke: color, strokeWidth: 1.8, fill: 'none', strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return (
    <Svg width={s} height={s} viewBox="0 0 24 24" accessibilityElementsHidden importantForAccessibility="no">
      {name === 'home' && <Path {...p} d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" />}
      {name === 'box' && <Path {...p} d="M6 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM4 10h16M8 6.5v1M8 13v2" />}
      {name === 'tray' && <Path {...p} d="M3 13a9 9 0 0 1 18 0M4 13h16M10 4.5a2 2 0 0 1 4 0M6 17h12" />}
      {name === 'cart' && <Path {...p} d="M4 5h2l2 10h10l2-7H7M10 19.5a.5.5 0 1 0 0 .01M17 19.5a.5.5 0 1 0 0 .01" />}
      {name === 'book' && <Path {...p} d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10M9 8h5" />}
      {name === 'gear' && (
        <Path
          {...p}
          d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"
        />
      )}
      {name === 'camera' && <Path {...p} d="M4 8h3l2-3h6l2 3h3v11H4zM12 10a3 3 0 1 0 0 6 3 3 0 0 0 0-6z" />}
      {name === 'bag' && <Path {...p} d="M5 8h14l-1 12H6zM9 8V6a3 3 0 0 1 6 0v2" />}
      {name === 'clock' && <Path {...p} d="M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM12 7.5V12l3 2" />}
      {name === 'check' && <Path {...p} d="M5 12.5l5 5 9-10" />}
      {name === 'close' && <Path {...p} d="M6 6l12 12M18 6l-12 12" />}
      {name === 'plus' && <Path {...p} d="M12 5v14M5 12h14" />}
      {name === 'minus' && <Path {...p} d="M5 12h14" />}
      {name === 'arrow-right' && <Path {...p} d="M5 12h14M13 6l6 6-6 6" />}
      {name === 'arrow-left' && <Path {...p} d="M19 12H5M11 6l-6 6 6 6" />}
      {name === 'arrow-up-right' && <Path {...p} d="M7 17L17 7M9 7h8v8" />}
      {name === 'chevron-left' && <Path {...p} d="M15 6l-6 6 6 6" />}
      {name === 'chevron-right' && <Path {...p} d="M9 6l6 6-6 6" />}
      {name === 'compass' && <Path {...p} d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM15.5 8.5l-2 5.5-5.5 2 2-5.5z" />}
      {name === 'shield' && <Path {...p} d="M12 3l7 3v5.5c0 4.5-3 7.8-7 9.5-4-1.7-7-5-7-9.5V6z" />}
      {name === 'sliders' && <Path {...p} d="M4 7h16M4 17h16M9 4v6M15 14v6" />}
      {name === 'search' && <Path {...p} d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4" />}
      {name === 'trash' && <Path {...p} d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5" />}
      {name === 'edit' && <Path {...p} d="M4 20h4l10-10-4-4L4 16v4zM13.5 6.5l4 4" />}
      {name === 'eye' && <Path {...p} d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6zM12 9.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6z" />}
      {name === 'eye-off' && (
        <Path
          {...p}
          d="M3 3l18 18M10.6 10.6a2.8 2.8 0 0 0 3.8 3.8M9.9 5.3A9.7 9.7 0 0 1 12 5c6 0 9.5 7 9.5 7a16.4 16.4 0 0 1-3.2 4.2M6.2 7.2A16.7 16.7 0 0 0 2.5 12s3.5 7 9.5 7a9.7 9.7 0 0 0 4.3-1"
        />
      )}
      {name === 'flame' && (
        <Path {...p} d="M12 3s5 4.2 5 9.5a5 5 0 1 1-10 0c0-2.4 1.1-4.3 2.3-5.8.2 1.8 1.2 2.8 2.2 2.8 0-2.7.5-4.8.5-6.5z" />
      )}
      {name === 'menu' && <Path {...p} d="M4 7h16M4 12h16M4 17h16" />}
      {name === 'alert-triangle' && <Path {...p} d="M12 4L3 19h18zM12 10v4M12 16.8h.01" />}
    </Svg>
  );
}

const styles = StyleSheet.create({
  badge: { flexDirection: 'row', alignItems: 'center', gap: 6, borderRadius: radius.sm, alignSelf: 'flex-start', maxWidth: '100%', flexShrink: 1 },
  dot: { width: 8, height: 8, borderRadius: radius.pill },
});
