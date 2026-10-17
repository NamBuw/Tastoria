import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Path, Rect } from 'react-native-svg';

import type { Schemas } from '@/api/client';
import { font, radius, space, useTheme } from '@/theme';

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

/** Colour dot ALWAYS with its text label (WCAG 1.4.1). */
export function FreshBadge({ value, small }: { value: Freshness; small?: boolean }) {
  const { c } = useTheme();
  const color = c.fresh[value];
  return (
    <View style={styles.badge} accessibilityLabel={`Độ tươi: ${FRESH_LABEL[value]}`}>
      <View
        style={[
          styles.dot,
          value === 'kiem_tra' || value === 'chua_ro'
            ? { borderWidth: 2, borderColor: color, backgroundColor: 'transparent' }
            : { backgroundColor: color },
        ]}
      />
      <Text style={{ fontFamily: font.medium, fontSize: small ? 13 : 15, color }}>{FRESH_LABEL[value]}</Text>
    </View>
  );
}

// ---- grams --------------------------------------------------------------------------------------

export function fmtG(min: number, max: number): string {
  const r = (x: number) => (x >= 100 ? Math.round(x / 10) * 10 : Math.round(x));
  const a = r(min);
  const b = r(max);
  if (a === b) return `${a} g`;
  return `${a}–${b} g`;
}

export const SLOT_LABEL: Record<'man' | 'rau' | 'canh', string> = { man: 'Mặn', rau: 'Rau', canh: 'Canh' };

// ---- tray ---------------------------------------------------------------------------------------

type TrayItem = Pick<Schemas['MealPlanItem'], 'id' | 'slot' | 'recipe_name_vi'>;

/** Top-down round tray: rice bowl in the centre, 2–3 dishes around (v1 §5.2 motif). */
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
  const angles = sorted.length === 3 ? [-90, 150, 30] : sorted.length === 2 ? [-90, 90] : [-90];
  const dishD = S * (compact ? 0.34 : 0.38);
  const bowlD = S * 0.28;
  const r = S * 0.29;
  return (
    <View
      style={{ width: S, height: S, alignSelf: 'center' }}
      accessibilityLabel={`Mâm: ${sorted.map((i) => `${SLOT_LABEL[i.slot]} ${i.recipe_name_vi}`).join(', ')}, cơm ở giữa`}>
      <View
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: S / 2,
          backgroundColor: c.tray,
          borderWidth: S * 0.035,
          borderColor: c.trayRim,
        }}
      />
      <View
        style={[
          styles.circle,
          {
            width: bowlD,
            height: bowlD,
            borderRadius: bowlD / 2,
            left: S / 2 - bowlD / 2,
            top: S / 2 - bowlD / 2,
            backgroundColor: c.rice,
            borderColor: c.trayRim,
          },
        ]}>
        <Text style={{ fontFamily: font.semibold, color: c.text, fontSize: compact ? 12 : 15 }}>Cơm</Text>
        {bowls && !compact ? (
          <Text style={{ fontFamily: font.regular, color: c.muted, fontSize: 12, textAlign: 'center' }}>
            {fmtBowls(bowls)} bát/người
          </Text>
        ) : null}
      </View>
      {sorted.map((it, i) => {
        const a = (angles[i] * Math.PI) / 180;
        const cx = S / 2 + r * Math.cos(a);
        const cy = S / 2 + r * Math.sin(a);
        const content = (
          <>
            <Text style={{ fontFamily: font.semibold, color: c.accent, fontSize: compact ? 11 : 13 }}>
              {SLOT_LABEL[it.slot]}
            </Text>
            {!compact ? (
              <Text
                numberOfLines={3}
                style={{ fontFamily: font.medium, color: c.text, fontSize: 13, lineHeight: 17, textAlign: 'center' }}>
                {it.recipe_name_vi}
              </Text>
            ) : null}
          </>
        );
        const style = [
          styles.circle,
          {
            width: dishD,
            height: dishD,
            borderRadius: dishD / 2,
            left: cx - dishD / 2,
            top: cy - dishD / 2,
            backgroundColor: c.dish,
            borderColor: c.accent,
            padding: 6,
          },
        ];
        return onPressItem ? (
          <Pressable
            key={it.id}
            testID={`tray-dish-${it.slot}`}
            accessibilityRole="button"
            accessibilityLabel={`${SLOT_LABEL[it.slot]}: ${it.recipe_name_vi}. Chạm để xem, đổi món hoặc xem thiếu gì`}
            onPress={() => onPressItem(it)}
            style={({ pressed }) => [...style, { opacity: pressed ? 0.85 : 1 }]}>
            {content}
          </Pressable>
        ) : (
          <View key={it.id} style={style}>
            {content}
          </View>
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
        <T v="label">
          {Math.round(low)}–{Math.round(high)} kcal
        </T>
      </View>
      <View
        style={{ height: 14, borderRadius: 7, backgroundColor: c.surfaceAlt, overflow: 'hidden' }}
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
            borderRadius: 7,
          }}
        />
        {target ? (
          <View style={{ position: 'absolute', left: pct(target), top: -2, bottom: -2, width: 3, backgroundColor: c.text }} />
        ) : null}
      </View>
      <T v="small" tone="muted">
        {target
          ? `Vạch đen: mục tiêu bữa ${Math.round(target)} kcal · ${status}`
          : 'Chưa có mục tiêu năng lượng. Đặt trong Cài đặt › Hồ sơ.'}
      </T>
    </View>
  );
}

// ---- icons (thin, rounded strokes) ---------------------------------------------------------------

type IconName = 'home' | 'box' | 'tray' | 'cart' | 'book' | 'gear' | 'camera' | 'bag' | 'clock';

export function Icon({ name, color, size: s = 24 }: { name: IconName; color: string; size?: number }) {
  const p = { stroke: color, strokeWidth: 1.8, fill: 'none', strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return (
    <Svg width={s} height={s} viewBox="0 0 24 24" accessibilityElementsHidden importantForAccessibility="no">
      {name === 'home' && <Path {...p} d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" />}
      {name === 'box' && (
        <>
          <Rect {...p} x="4" y="3" width="16" height="18" rx="2" />
          <Path {...p} d="M4 10h16M8 6.5v1M8 13v2" />
        </>
      )}
      {name === 'tray' && (
        <>
          <Circle {...p} cx="12" cy="12" r="9" />
          <Circle {...p} cx="12" cy="12" r="2.5" />
          <Circle {...p} cx="12" cy="6.5" r="2" />
          <Circle {...p} cx="7.5" cy="15" r="2" />
          <Circle {...p} cx="16.5" cy="15" r="2" />
        </>
      )}
      {name === 'cart' && <Path {...p} d="M4 5h2l2 10h10l2-7H7M10 19.5a.5.5 0 1 0 0 .01M17 19.5a.5.5 0 1 0 0 .01" />}
      {name === 'book' && <Path {...p} d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10M9 8h5" />}
      {name === 'gear' && (
        <>
          <Circle {...p} cx="12" cy="12" r="3" />
          <Path
            {...p}
            d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"
          />
        </>
      )}
      {name === 'camera' && (
        <>
          <Path {...p} d="M4 8h3l2-3h6l2 3h3v11H4z" />
          <Circle {...p} cx="12" cy="13" r="3.5" />
        </>
      )}
      {name === 'bag' && <Path {...p} d="M5 8h14l-1 12H6zM9 8V6a3 3 0 0 1 6 0v2" />}
      {name === 'clock' && (
        <>
          <Circle {...p} cx="12" cy="12" r="8.5" />
          <Path {...p} d="M12 7.5V12l3 2" />
        </>
      )}
    </Svg>
  );
}

const styles = StyleSheet.create({
  badge: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 12, height: 12, borderRadius: 6 },
  circle: { position: 'absolute', alignItems: 'center', justifyContent: 'center', borderWidth: 2 },
  pill: { borderRadius: radius.pill },
});
