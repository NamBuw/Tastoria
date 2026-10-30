import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Defs, Ellipse, G, Path, RadialGradient, Rect, Stop } from 'react-native-svg';

import type { Schemas } from '@/api/client';
import { font, radius, space, useTheme, type Palette } from '@/theme';

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
    <View
      style={[styles.badge, { backgroundColor: c.freshSoft[value], paddingHorizontal: small ? 8 : 10, paddingVertical: small ? 2 : 4 }]}
      accessibilityLabel={`Độ tươi: ${FRESH_LABEL[value]}`}>
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

/** One dish drawn from above in a 100×100 box: Bát Tràng plate/bowl with a simple food shape per slot. */
function DishArt({ slot, c }: { slot: 'man' | 'rau' | 'canh'; c: Palette }) {
  const leaf = c.herb;
  if (slot === 'canh')
    return (
      <G>
        <Circle cx="50" cy="50" r="47" fill={c.dish} stroke={c.glaze} strokeWidth="3" />
        <Circle cx="50" cy="50" r="40" fill="none" stroke={c.glaze} strokeWidth="1.2" strokeDasharray="3 5" />
        <Circle cx="50" cy="50" r="33" fill="#D9B45A" opacity={0.55} />
        <Circle cx="50" cy="50" r="33" fill="none" stroke="#B88B2E" strokeWidth="1" opacity={0.6} />
        <Ellipse cx="40" cy="44" rx="9" ry="4.5" fill={leaf} transform="rotate(-30 40 44)" />
        <Ellipse cx="58" cy="56" rx="8" ry="4" fill={leaf} transform="rotate(25 58 56)" />
        <Ellipse cx="55" cy="38" rx="6" ry="3" fill={leaf} opacity={0.85} transform="rotate(60 55 38)" />
        <Circle cx="44" cy="60" r="4" fill="#C77A55" />
        <Circle cx="62" cy="44" r="3.2" fill="#C77A55" />
        <Circle cx="36" cy="54" r="2" fill="#FFFFFF" opacity={0.6} />
      </G>
    );
  if (slot === 'rau')
    return (
      <G>
        <Circle cx="50" cy="50" r="47" fill={c.dish} stroke={c.glaze} strokeWidth="3" />
        <Circle cx="50" cy="50" r="38" fill="none" stroke={c.glaze} strokeWidth="1" opacity={0.5} />
        {[0, 45, 90, 135, 180, 225, 270, 315].map((a, i) => (
          <Ellipse
            key={a}
            cx="50"
            cy={i % 2 ? 33 : 30}
            rx="8"
            ry="17"
            fill={i % 2 ? leaf : '#4E9A5C'}
            transform={`rotate(${a} 50 50)`}
          />
        ))}
        <Circle cx="50" cy="50" r="9" fill="#9CCB7A" />
      </G>
    );
  return (
    <G>
      <Ellipse cx="50" cy="50" rx="47" ry="47" fill={c.dish} stroke={c.glaze} strokeWidth="3" />
      <Path d="M50 9 l3 5 -3 5 -3 -5z M50 81 l3 5 -3 5 -3 -5z M9 50 l5 -3 5 3 -5 3z M81 50 l5 -3 5 3 -5 3z" fill={c.glaze} />
      <Rect x="30" y="32" width="18" height="14" rx="5" fill="#9A5A2E" transform="rotate(-12 39 39)" />
      <Rect x="50" y="30" width="17" height="13" rx="5" fill="#B06A35" transform="rotate(14 58 36)" />
      <Rect x="34" y="50" width="17" height="14" rx="5" fill="#B06A35" transform="rotate(8 42 57)" />
      <Rect x="53" y="49" width="16" height="14" rx="5" fill="#8C4E26" transform="rotate(-10 61 56)" />
      <Circle cx="48" cy="47" r="2.2" fill={leaf} />
      <Circle cx="60" cy="45" r="1.8" fill={leaf} />
      <Circle cx="44" cy="62" r="1.8" fill={leaf} />
      <Circle cx="52" cy="58" r="1.5" fill="#D9472F" />
    </G>
  );
}

/** Top-down lacquered round tray (mâm): rice bowl in the centre, 2–3 dishes around (v1 §5.2 motif). */
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
  const angles = sorted.length === 3 ? [-90, 150, 30] : sorted.length === 2 ? [180, 0] : [-90];
  const k = S / 100;
  const dishD = 31; // in tray units
  const R = 27.5;
  const pos = sorted.map((_, i) => {
    const a = (angles[i] * Math.PI) / 180;
    return { x: 50 + R * Math.cos(a), y: 50 + R * Math.sin(a) };
  });
  return (
    <View
      style={{ width: S, height: S, alignSelf: 'center' }}
      accessibilityLabel={`Mâm: ${sorted.map((i) => `${SLOT_LABEL[i.slot]} ${i.recipe_name_vi}`).join(', ')}, cơm ở giữa`}>
      <Svg width={S} height={S} viewBox="0 0 100 100" accessibilityElementsHidden importantForAccessibility="no">
        <Defs>
          <RadialGradient id="lacq" cx="42%" cy="38%" r="70%">
            <Stop offset="0" stopColor={c.trayGrain} />
            <Stop offset="1" stopColor={c.tray} />
          </RadialGradient>
        </Defs>
        <Circle cx="50" cy="51.2" r="49" fill="#000" opacity={0.12} />
        <Circle cx="50" cy="50" r="49" fill={c.trayRim} />
        <Circle cx="50" cy="50" r="46" fill="url(#lacq)" />
        <Circle cx="50" cy="50" r="44.2" fill="none" stroke={c.trayRim} strokeWidth="0.5" opacity={0.7} />
        {[36, 30, 22].map((r) => (
          <Circle key={r} cx="50" cy="50" r={r} fill="none" stroke="#000" strokeWidth="0.35" opacity={0.08} />
        ))}
        <Path d="M20 26 A40 40 0 0 1 46 9" stroke="#FFFFFF" strokeWidth="1.6" fill="none" opacity={0.18} strokeLinecap="round" />
        {sorted.map((it, i) => (
          <G key={it.id}>
            <Circle cx={pos[i].x + 0.8} cy={pos[i].y + 1.6} r={dishD / 2} fill="#000" opacity={0.22} />
            <G transform={`translate(${pos[i].x - dishD / 2} ${pos[i].y - dishD / 2}) scale(${dishD / 100})`}>
              <DishArt slot={it.slot} c={c} />
            </G>
          </G>
        ))}
        {/* rice bowl */}
        <Circle cx="50.6" cy="51.4" r="11.5" fill="#000" opacity={0.22} />
        <Circle cx="50" cy="50" r="11.5" fill={c.dish} stroke={c.glaze} strokeWidth="1" />
        <Circle cx="50" cy="50" r="9.5" fill="none" stroke={c.glaze} strokeWidth="0.4" strokeDasharray="1 1.6" />
        <Circle cx="50" cy="50" r="8" fill={c.rice} />
        {[
          [47, 47], [52, 46], [49, 51], [54, 50], [46, 53], [51, 54], [50, 48.5],
        ].map(([x, y], j) => (
          <Ellipse key={j} cx={x} cy={y} rx="1.1" ry="0.55" fill="#E4DED0" transform={`rotate(${j * 40} ${x} ${y})`} />
        ))}
      </Svg>
      {!compact && bowls ? (
        <View pointerEvents="none" style={[styles.tag, { left: S / 2 - 46, width: 92, top: S / 2 + 12 * k, backgroundColor: c.surface }]}>
          <Text style={{ fontFamily: font.semibold, fontSize: 12, color: c.text }}>Cơm {fmtBowls(bowls)} bát</Text>
        </View>
      ) : null}
      {sorted.map((it, i) => {
        const d = dishD * k;
        const left = pos[i].x * k - d / 2;
        const top = pos[i].y * k - d / 2;
        const tag = compact ? null : (
          <View pointerEvents="none" style={[styles.tag, { backgroundColor: c.surface, bottom: -10, alignSelf: 'center' }]}>
            <Text style={{ fontFamily: font.semibold, fontSize: 12, color: c.accent }}>{SLOT_LABEL[it.slot]}</Text>
          </View>
        );
        return onPressItem ? (
          <Pressable
            key={it.id}
            testID={`tray-dish-${it.slot}`}
            accessibilityRole="button"
            accessibilityLabel={`${SLOT_LABEL[it.slot]}: ${it.recipe_name_vi}. Chạm để xem, đổi món hoặc xem thiếu gì`}
            onPress={() => onPressItem(it)}
            style={({ pressed }) => [styles.hit, { left, top, width: d, height: d, borderRadius: d / 2, transform: [{ scale: pressed ? 0.96 : 1 }] }]}>
            {tag}
          </Pressable>
        ) : (
          <View key={it.id} style={[styles.hit, { left, top, width: d, height: d }]}>
            {tag}
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
        style={{ height: 12, borderRadius: 6, backgroundColor: c.surfaceAlt, overflow: 'hidden' }}
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
            backgroundColor: c.herb,
            borderRadius: 6,
          }}
        />
        {target ? (
          <View style={{ position: 'absolute', left: pct(target), top: -2, bottom: -2, width: 3, backgroundColor: c.text }} />
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
  badge: { flexDirection: 'row', alignItems: 'center', gap: 6, borderRadius: 999, alignSelf: 'flex-start' },
  dot: { width: 10, height: 10, borderRadius: 5 },
  hit: { position: 'absolute', alignItems: 'center', justifyContent: 'flex-end' },
  tag: { position: 'absolute', paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, alignItems: 'center', boxShadow: '0 1px 3px rgba(0,0,0,0.25)' },
  pill: { borderRadius: radius.pill },
});
