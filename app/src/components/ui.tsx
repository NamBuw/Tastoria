import { useEffect, useId, useState, type ReactNode } from 'react';
import {
  AccessibilityInfo,
  ActivityIndicator,
  Animated,
  Easing,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { containerMaxWidth, font, radius, size, space, TOUCH, useLayout, useTheme } from '@/theme';

import { Icon } from './domain';

// ---- text ---------------------------------------------------------------------------------------

type Variant = 'body' | 'small' | 'label' | 'title' | 'h1' | 'h2' | 'huge';
const VARIANTS: Record<Variant, TextStyle> = {
  small: { fontSize: 13, lineHeight: 19, fontFamily: font.regular },
  body: { fontSize: 15, lineHeight: 24, fontFamily: font.regular },
  label: { fontSize: 15, lineHeight: 22, fontFamily: font.semibold },
  title: { fontSize: 17, lineHeight: 24, fontFamily: font.semibold, letterSpacing: -0.2 },
  h2: { fontSize: size.lg, lineHeight: 28, fontFamily: font.displaySemibold, letterSpacing: -0.3 },
  h1: { fontSize: size.xl, lineHeight: 32, fontFamily: font.displaySemibold, letterSpacing: -0.4 },
  huge: { fontSize: size.huge, lineHeight: 42, fontFamily: font.displaySemibold, letterSpacing: -0.6 },
};

type Tone =
  | 'text'
  | 'muted'
  | 'accent'
  | 'danger'
  | 'onAccent'
  | 'herb'
  | 'onEditorial'
  | 'onLime'
  | 'onStory'
  | 'onStoryMuted'
  | 'info'
  | 'warn';

export function T({
  v = 'body',
  tone = 'text',
  tabular,
  'aria-level': ariaLevel,
  style,
  ...p
}: TextProps & { v?: Variant; tone?: Tone; tabular?: boolean; 'aria-level'?: 1 | 2 | 3 | 4 | 5 | 6 }) {
  const { c } = useTheme();
  const isHeader = p.accessibilityRole === 'header';
  const defaultLevel = isHeader ? (v === 'h1' || v === 'huge' ? 1 : v === 'h2' ? 2 : 3) : undefined;
  const level = ariaLevel ?? defaultLevel;
  const webAria = Platform.OS === 'web' && level ? ({ 'aria-level': level } as object) : undefined;
  return (
    <Text
      {...p}
      {...webAria}
      style={[
        VARIANTS[v],
        { color: c[tone] },
        tabular ? { fontVariant: ['tabular-nums'] } : null,
        style,
      ]}
    />
  );
}

// ---- layout -------------------------------------------------------------------------------------

export function Screen({
  children,
  scroll = true,
  footer,
  testID,
  scrollKey,
  variant = 'workspace',
}: {
  children: ReactNode;
  scroll?: boolean;
  footer?: ReactNode;
  testID?: string;
  scrollKey?: string;
  variant?: 'workspace' | 'focused';
}) {
  const { c } = useTheme();
  const { width, padX } = useLayout();
  const maxWidth = containerMaxWidth(width, variant);
  const inner = (
    <View
      testID="screen-inner"
      style={[styles.inner, maxWidth ? { maxWidth } : { maxWidth: '100%' }, !scroll ? { flex: 1 } : null]}>
      {children}
    </View>
  );
  return (
    <SafeAreaView edges={['left', 'right', 'bottom']} style={{ flex: 1, backgroundColor: 'transparent' }} testID={testID}>
      {scroll ? (
        <ScrollView
          key={scrollKey}
          contentContainerStyle={[styles.scroll, { paddingHorizontal: padX }]}
          keyboardShouldPersistTaps="handled">
          {inner}
        </ScrollView>
      ) : (
        <View style={[styles.scroll, { flex: 1, paddingHorizontal: padX }]}>{inner}</View>
      )}
      {footer ? (
        <View style={[styles.footer, { backgroundColor: c.surface, borderTopColor: c.hairline, paddingHorizontal: padX }]}>
          <View style={[styles.footerInner, maxWidth ? { maxWidth } : { maxWidth: '100%' }]}>{footer}</View>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

export function Card({
  children,
  style,
  testID,
  variant = 'default',
}: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  variant?: 'default' | 'ledger';
}) {
  const { c } = useTheme();
  return (
    <View
      testID={testID}
      style={[
        styles.card,
        {
          backgroundColor: c.surfaceCard,
          borderColor: variant === 'ledger' ? c.border : c.hairline,
          borderWidth: variant === 'ledger' ? 1.5 : 1,
        },
        style,
      ]}>
      {children}
    </View>
  );
}

/**
 * Clean elevated card container for meal summary or nutrition highlights.
 */
export function BroadsheetLedgerFrame({
  title,
  rightText,
  accentTone = 'herb',
  testID,
  style,
  innerStyle,
  children,
}: {
  title?: string;
  rightText?: string;
  accentTone?: 'herb' | 'accent' | 'border';
  testID?: string;
  style?: StyleProp<ViewStyle>;
  innerStyle?: StyleProp<ViewStyle>;
  children: ReactNode;
}) {
  const { c } = useTheme();
  const titleColor = accentTone === 'herb' ? c.herb : accentTone === 'accent' ? c.accent : c.text;
  return (
    <View
      testID={testID}
      style={[
        {
          borderWidth: 1,
          borderColor: c.hairline,
          borderRadius: radius.lg,
          backgroundColor: c.surfaceCard,
          overflow: 'hidden',
        },
        style,
      ]}>
      <View
        style={[
          {
            padding: space.lg,
            gap: space.md,
          },
          innerStyle,
        ]}>
        {title ? (
          <View
            style={{
              flexDirection: 'row',
              flexWrap: 'wrap',
              justifyContent: 'space-between',
              alignItems: 'baseline',
              borderBottomWidth: 1,
              borderBottomColor: c.hairline,
              paddingBottom: space.sm,
              gap: space.sm,
            }}>
            <T
              v="h2"
              accessibilityRole="header"
              style={{ color: titleColor, fontFamily: font.semibold, flexShrink: 1 }}>
              {title}
            </T>
            {rightText ? (
              <T v="small" tone="accent" tabular style={{ flexShrink: 0, fontFamily: font.semibold }}>
                {rightText}
              </T>
            ) : null}
          </View>
        ) : null}
        {children}
      </View>
    </View>
  );
}

export function Row({ children, style, gap = space.sm }: { children: ReactNode; style?: StyleProp<ViewStyle>; gap?: number }) {
  return <View style={[{ flexDirection: 'row', alignItems: 'center', gap, flexWrap: 'wrap' }, style]}>{children}</View>;
}

export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <View style={{ gap: space.md }}>
      <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap', minHeight: 32 }}>
        <T v="h2" accessibilityRole="header" style={{ flexShrink: 1 }}>
          {title}
        </T>
        {right}
      </Row>
      {children}
    </View>
  );
}

// ---- buttons ------------------------------------------------------------------------------------

type BtnKind = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({
  label,
  onPress,
  kind = 'primary',
  big,
  compact,
  loading,
  disabled,
  icon,
  iconRight,
  sub,
  testID,
  style,
  accessibilityLabel,
}: {
  label: string;
  onPress?: () => void;
  kind?: BtnKind;
  big?: boolean;
  compact?: boolean;
  loading?: boolean;
  disabled?: boolean;
  icon?: ReactNode;
  iconRight?: ReactNode;
  sub?: string;
  testID?: string;
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}) {
  const { c } = useTheme();
  const off = disabled || loading;
  const bg =
    off && (kind === 'primary' || kind === 'danger')
      ? c.surfaceAlt
      : kind === 'primary'
        ? c.accent
        : kind === 'danger'
          ? c.danger
          : kind === 'secondary'
            ? c.surface
            : 'transparent';
  const fg =
    off && (kind === 'primary' || kind === 'danger')
      ? c.muted
      : kind === 'primary' || kind === 'danger'
        ? c.onAccent
        : kind === 'secondary'
          ? c.text
          : c.accent;
  const border =
    off && (kind === 'primary' || kind === 'danger')
      ? c.hairline
      : kind === 'secondary'
        ? c.border
        : 'transparent';
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: !!off, busy: !!loading }}
      disabled={off}
      onPress={onPress}
      style={({ pressed }) => [
        styles.btn,
        big && styles.btnBig,
        compact && { minHeight: 38, paddingHorizontal: space.md, paddingVertical: 6 },
        {
          backgroundColor:
            pressed && !off && kind === 'primary'
              ? c.accentDisplay
              : pressed && !off && kind === 'secondary'
                ? c.surfaceAlt
                : bg,
          borderColor: border,
          opacity: off && kind === 'secondary' ? 0.55 : 1,
          transform: [{ scale: pressed && !off ? 0.98 : 1 }],
        },
        style,
      ]}>
      {loading ? <ActivityIndicator color={fg} /> : icon}
      <View style={{ alignItems: big && icon ? 'flex-start' : 'center', flexShrink: 1 }}>
        <Text
          style={[
            big ? VARIANTS.title : VARIANTS.label,
            { color: fg, textAlign: 'center', fontSize: compact ? size.sm : size.md, lineHeight: compact ? 20 : 24 },
          ]}>
          {label}
        </Text>
        {sub ? <Text style={[VARIANTS.small, { color: fg }]}>{sub}</Text> : null}
      </View>
      {!loading ? iconRight : null}
    </Pressable>
  );
}

export function LinkButton({ label, onPress, testID }: { label: string; onPress: () => void; testID?: string }) {
  const { c } = useTheme();
  return (
    <Pressable
      testID={testID}
      accessibilityRole="link"
      onPress={onPress}
      style={{ minHeight: TOUCH, justifyContent: 'center', paddingHorizontal: space.xs }}>
      <Text style={[VARIANTS.label, { color: c.accent }]}>{label}</Text>
    </Pressable>
  );
}

// ---- chips --------------------------------------------------------------------------------------

export function Chip({
  label,
  selected,
  onPress,
  left,
  testID,
  disabled,
}: {
  label: string;
  selected?: boolean;
  onPress?: () => void;
  left?: ReactNode;
  testID?: string;
  disabled?: boolean;
}) {
  const { c } = useTheme();
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={disabled || !onPress}
      accessibilityRole={onPress ? (selected === undefined ? 'button' : 'checkbox') : undefined}
      accessibilityState={selected === undefined ? undefined : { checked: selected, disabled }}
      style={({ pressed }) => [
        styles.chip,
        {
          backgroundColor: selected ? c.accentSoft : c.surface,
          borderColor: selected ? c.accent : c.hairline,
          borderWidth: 1,
          opacity: disabled ? 0.5 : pressed ? 0.85 : 1,
        },
      ]}>
      {selected ? <Icon name="check" size={16} color={c.accent} /> : null}
      {left}
      <Text style={[selected ? VARIANTS.label : VARIANTS.body, { color: selected ? c.accent : c.text, flexShrink: 1 }]}>
        {label}
      </Text>
    </Pressable>
  );
}

export function Segmented<V extends string | number | boolean | null>({
  options,
  value,
  onChange,
  label,
  column,
  children,
}: {
  options: readonly (readonly [V, string])[];
  value: V | undefined;
  onChange: (v: V) => void;
  label?: string;
  column?: number;
  children?: ReactNode;
}) {
  const radios = options.map(([v, l]) => <Radio key={String(v)} label={l} selected={value === v} onPress={() => onChange(v)} />);
  return (
    <View style={{ gap: space.xs }} accessibilityRole="radiogroup" accessibilityLabel={label}>
      {label ? <T v="label">{label}</T> : null}
      {column === undefined ? <Row>{radios}</Row> : <View style={{ gap: column }}>{radios}</View>}
      {children}
    </View>
  );
}

export function Radio({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const { c } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="radio"
      accessibilityState={{ selected, checked: selected }}
      style={[
        styles.chip,
        { backgroundColor: selected ? c.accentSoft : c.surface, borderColor: selected ? c.accent : c.hairline, borderWidth: 1 },
      ]}>
      <View style={[styles.radioDot, { borderColor: selected ? c.accent : c.border }]}>
        {selected ? <View style={[styles.radioInner, { backgroundColor: c.accent }]} /> : null}
      </View>
      <Text style={[selected ? VARIANTS.label : VARIANTS.body, { color: c.text, flexShrink: 1 }]}>{label}</Text>
    </Pressable>
  );
}

export function UnderlineTabs<V extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly (readonly [V, string, string?])[];
  value: V;
  onChange: (v: V) => void;
  label?: string;
}) {
  const { c } = useTheme();
  return (
    <View
      accessibilityRole="tablist"
      accessibilityLabel={label}
      style={{
        flexDirection: 'row',
        flexWrap: 'wrap',
        borderBottomWidth: 1,
        borderBottomColor: c.hairline,
        gap: space.lg,
      }}>
      {options.map(([v, lbl, tid]) => {
        const active = value === v;
        return (
          <Pressable
            key={v}
            testID={tid}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            onPress={() => onChange(v)}
            style={({ pressed }) => ({
              minHeight: 44,
              justifyContent: 'center',
              paddingVertical: space.sm,
              paddingHorizontal: 2,
              borderBottomWidth: 2,
              borderBottomColor: active ? c.accent : 'transparent',
              marginBottom: -1,
              opacity: pressed ? 0.75 : 1,
            })}>
            <Text style={[active ? VARIANTS.label : VARIANTS.body, { color: active ? c.text : c.muted }]}>
              {lbl}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function HairlineSegmented<V extends string | number>({
  options,
  value,
  onChange,
  label,
  testID,
  disabled,
}: {
  options: readonly (readonly [V, string])[];
  value: V;
  onChange: (v: V) => void;
  label?: string;
  testID?: string;
  disabled?: boolean;
}) {
  const { c } = useTheme();
  return (
    <View style={{ gap: space.xs, opacity: disabled ? 0.6 : 1 }}>
      {label ? <T v="small" tone="muted">{label}</T> : null}
      <View
        testID={testID}
        accessibilityRole="radiogroup"
        accessibilityLabel={label}
        style={{
          flexDirection: 'row',
          borderWidth: 1,
          borderColor: c.hairline,
          borderRadius: radius.sm,
          overflow: 'hidden',
          backgroundColor: c.surface,
        }}>
        {options.map(([v, lbl], idx) => {
          const active = value === v;
          return (
            <Pressable
              key={String(v)}
              disabled={disabled}
              accessibilityRole="radio"
              accessibilityState={{ selected: active, checked: active, disabled }}
              onPress={() => onChange(v)}
              style={({ pressed }) => ({
                flex: 1,
                minHeight: 44,
                paddingHorizontal: space.sm,
                alignItems: 'center',
                justifyContent: 'center',
                borderLeftWidth: idx > 0 ? 1 : 0,
                borderLeftColor: c.hairline,
                backgroundColor: active ? c.accentSoft : pressed && !disabled ? c.surfaceAlt : c.surface,
              })}>
              <Text
                numberOfLines={2}
                style={[
                  active ? VARIANTS.label : VARIANTS.body,
                  { color: active ? c.accent : c.text, textAlign: 'center', fontVariant: ['tabular-nums'] },
                ]}>
                {lbl}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export function ReceiptCheckRow({
  label,
  rightText,
  checked,
  onPress,
  testID,
  first,
}: {
  label: string;
  rightText: string;
  checked: boolean;
  onPress: () => void;
  testID?: string;
  first?: boolean;
}) {
  const { c } = useTheme();
  return (
    <Pressable
      testID={testID}
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 44,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: space.sm,
        paddingVertical: space.xs,
        paddingHorizontal: space.xs,
        borderTopWidth: first ? 1 : 0,
        borderBottomWidth: 1,
        borderColor: c.hairline,
        backgroundColor: checked ? c.accentSoft : pressed ? c.surfaceAlt : 'transparent',
      })}>
      <Row gap={space.sm} style={{ flex: 1, minWidth: 0, flexWrap: 'nowrap' }}>
        <View
          style={{
            width: 18,
            height: 18,
            borderRadius: radius.sm,
            borderWidth: 1.5,
            borderColor: checked ? c.accent : c.border,
            backgroundColor: checked ? c.accent : c.surface,
            alignItems: 'center',
            justifyContent: 'center',
          }}>
          {checked ? <Icon name="check" size={12} color={c.onAccent} /> : null}
        </View>
        <Text style={[checked ? VARIANTS.label : VARIANTS.body, { color: c.text, flexShrink: 1 }]}>
          {label}
        </Text>
      </Row>
      <Text style={[VARIANTS.label, { color: checked ? c.accent : c.muted, fontVariant: ['tabular-nums'] }]}>
        {rightText}
      </Text>
    </Pressable>
  );
}

export function Checkbox({
  checked,
  onChange,
  label,
  sub,
  testID,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  sub?: ReactNode;
  testID?: string;
  disabled?: boolean;
}) {
  const { c } = useTheme();
  return (
    <Pressable
      testID={testID}
      disabled={disabled}
      onPress={() => onChange(!checked)}
      accessibilityRole="checkbox"
      accessibilityState={{ checked, disabled }}
      style={{
        flexDirection: 'row',
        gap: space.md,
        minHeight: TOUCH,
        alignItems: 'flex-start',
        paddingVertical: space.sm,
        opacity: disabled ? 0.55 : 1,
      }}>
      <View
        style={[
          styles.box,
          { borderColor: checked ? c.accent : c.border, backgroundColor: checked ? c.accent : c.surface },
        ]}>
        {checked ? <Icon name="check" size={16} color={c.onAccent} /> : null}
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <T v="label">{label}</T>
        {sub}
      </View>
    </Pressable>
  );
}

// ---- inputs -------------------------------------------------------------------------------------

export function Field({
  label,
  error,
  hint,
  style,
  ...p
}: TextInputProps & { label: string; error?: string; hint?: string }) {
  const { c } = useTheme();
  const labelId = useId();
  return (
    <View style={{ gap: space.xs }}>
      <T v="label" nativeID={labelId}>
        {label}
      </T>
      <TextInput
        accessibilityLabel={label}
        aria-labelledby={labelId}
        placeholderTextColor={c.muted}
        {...p}
        style={[
          styles.input,
          { borderColor: error ? c.danger : c.hairline, color: c.text, backgroundColor: c.surface },
          style,
        ]}
      />
      {hint && !error ? <T v="small" tone="muted">{hint}</T> : null}
      {error ? (
        <T v="small" tone="danger" accessibilityLiveRegion="polite">
          {error}
        </T>
      ) : null}
    </View>
  );
}

export function Stepper({
  value,
  onChange,
  min,
  max,
  step = 1,
  label,
  format,
  testID,
}: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  label: string;
  format?: (v: number) => string;
  testID?: string;
}) {
  const { c } = useTheme();
  const btn = (kind: 'plus' | 'minus', next: number, a11y: string) => (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={a11y}
      disabled={next < min || next > max}
      onPress={() => onChange(next)}
      testID={testID ? `${testID}-${kind}` : undefined}
      style={({ pressed }) => [
        styles.stepBtn,
        { borderColor: c.hairline, backgroundColor: c.surface, opacity: next < min || next > max ? 0.4 : pressed ? 0.8 : 1 },
      ]}>
      <Icon name={kind} size={18} color={c.text} />
    </Pressable>
  );
  return (
    <View style={{ gap: space.xs }}>
      <T v="label">{label}</T>
      <Row gap={space.md} style={{ flexWrap: 'nowrap' }}>
        {btn('minus', value - step, `Giảm ${label.toLowerCase()}`)}
        <T v="h2" tabular style={{ minWidth: 64, textAlign: 'center' }} accessibilityLiveRegion="polite">
          {format ? format(value) : value}
        </T>
        {btn('plus', value + step, `Tăng ${label.toLowerCase()}`)}
      </Row>
    </View>
  );
}

// ---- states -------------------------------------------------------------------------------------

export function Loading({ label = 'Đang tải…', rows = 2 }: { label?: string; rows?: number }) {
  return (
    <View style={{ gap: space.sm }} accessibilityLiveRegion="polite" accessibilityLabel={label} accessibilityRole="progressbar">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height={68} />
      ))}
      <T v="small" tone="muted">
        {label}
      </T>
    </View>
  );
}

export function Skeleton({ height = 16, width = '100%', r = radius.md }: { height?: number; width?: number | `${number}%`; r?: number }) {
  const { c } = useTheme();
  const [o] = useState(() => new Animated.Value(0.55));
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(o, { toValue: 1, duration: 700, useNativeDriver: Platform.OS !== 'web' }),
        Animated.timing(o, { toValue: 0.55, duration: 700, useNativeDriver: Platform.OS !== 'web' }),
      ]),
    );
    if (!reduceMotion.current) loop.start();
    return () => loop.stop();
  }, [o]);
  return <Animated.View style={{ height, width, borderRadius: r, backgroundColor: c.surfaceAlt, opacity: o }} />;
}

const reduceMotion = { current: false as boolean | null };
AccessibilityInfo?.isReduceMotionEnabled?.().then((v) => (reduceMotion.current = v)).catch(() => undefined);

export function Rise({ children, delay = 0, style }: { children: ReactNode; delay?: number; style?: StyleProp<ViewStyle> }) {
  const [v] = useState(() => new Animated.Value(reduceMotion.current ? 1 : 0));
  useEffect(() => {
    if (reduceMotion.current) return;
    const anim = Animated.timing(v, {
      toValue: 1,
      duration: 300,
      delay,
      easing: Easing.bezier(0.22, 1, 0.36, 1),
      useNativeDriver: Platform.OS !== 'web',
    });
    anim.start();
    return () => anim.stop();
  }, [v, delay]);
  return (
    <Animated.View style={[style, { opacity: v, transform: [{ translateY: v.interpolate({ inputRange: [0, 1], outputRange: [8, 0] }) }] }]}>
      {children}
    </Animated.View>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { c } = useTheme();
  return (
    <View
      accessibilityRole="alert"
      style={[styles.card, { backgroundColor: c.dangerSoft, borderColor: c.danger, gap: space.sm }]}>
      <Row gap={space.sm} style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
        <View style={{ paddingTop: 2 }}>
          <Icon name="alert-triangle" size={18} color={c.danger} />
        </View>
        <T style={{ flex: 1 }}>{message}</T>
      </Row>
      {onRetry ? <Button kind="secondary" label="Thử lại" onPress={onRetry} /> : null}
    </View>
  );
}

export function Notice({ children, tone = 'info', testID }: { children: ReactNode; tone?: 'info' | 'ok' | 'warn'; testID?: string }) {
  const { c } = useTheme();
  const bg = tone === 'ok' ? c.okSoft : tone === 'warn' ? c.warnSoft : c.surfaceAlt;
  const border = tone === 'ok' ? c.herbSoft : tone === 'warn' ? c.warnSoft : c.hairline;
  return (
    <View
      testID={testID}
      style={[styles.card, { backgroundColor: bg, borderColor: border, borderRadius: radius.md, padding: space.md, gap: space.xs }]}>
      {children}
    </View>
  );
}

export function Empty({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  const { c } = useTheme();
  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: c.surfaceAlt,
          borderColor: c.hairline,
          alignItems: 'center',
          paddingVertical: space.xxl,
          paddingHorizontal: space.xl,
          gap: space.md,
        },
      ]}>
      <View
        style={{
          width: 48,
          height: 48,
          borderRadius: radius.md,
          backgroundColor: c.accentSoft,
          alignItems: 'center',
          justifyContent: 'center',
        }}>
        <Icon name="tray" size={22} color={c.accent} />
      </View>
      <View style={{ gap: space.xs, alignItems: 'center' }}>
        <T v="title" style={{ textAlign: 'center' }}>{title}</T>
        {body ? <T tone="muted" style={{ textAlign: 'center', maxWidth: 360 }}>{body}</T> : null}
      </View>
      {action ? <View style={{ marginTop: space.xs }}>{action}</View> : null}
    </View>
  );
}

// ---- sheet --------------------------------------------------------------------------------------

export function Sheet({
  visible,
  onClose,
  title,
  children,
  testID,
}: {
  visible: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  testID?: string;
}) {
  const { c } = useTheme();
  const { isTabletUp } = useLayout();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={[styles.overlay, { backgroundColor: c.overlay, justifyContent: isTabletUp ? 'center' : 'flex-end', padding: isTabletUp ? space.xl : 0 }]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Đóng" />
        <View
          testID={testID}
          accessibilityViewIsModal
            style={[
              styles.sheet,
              {
                backgroundColor: c.surface,
                borderColor: c.hairline,
                maxWidth: isTabletUp ? 560 : undefined,
                borderRadius: isTabletUp ? radius.lg : undefined,
              },
            ]}>
          {!isTabletUp ? <View style={{ alignSelf: 'center', width: 40, height: 4, borderRadius: radius.sm, backgroundColor: c.hairline, marginTop: -4 }} /> : null}
          <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
            <T v="h2" accessibilityRole="header" style={{ flexShrink: 1 }}>
              {title}
            </T>
            <Pressable
              onPress={onClose}
              accessibilityRole="button"
              accessibilityLabel="Đóng"
              style={{ minWidth: TOUCH, minHeight: TOUCH, alignItems: 'center', justifyContent: 'center' }}>
              <Icon name="close" size={20} color={c.muted} />
            </Pressable>
          </Row>
          <ScrollView contentContainerStyle={{ gap: space.md, paddingBottom: space.lg }} keyboardShouldPersistTaps="handled">
            {children}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

export function ProgressDots({ step, total, label }: { step: number; total: number; label: string }) {
  const { c } = useTheme();
  return (
    <View style={{ gap: space.xs }} accessibilityLabel={`Bước ${step} trên ${total}: ${label}`}>
      <T v="small" tone="muted">
        Bước {step}/{total}: {label}
      </T>
      <View style={{ flexDirection: 'row', gap: 6 }}>
        {Array.from({ length: total }, (_, i) => (
          <View
            key={i}
            style={{ flex: 1, height: 6, borderRadius: radius.sm, backgroundColor: i < step ? c.accent : c.surfaceAlt }}
          />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { flexGrow: 1, paddingHorizontal: space.lg, paddingTop: space.lg, paddingBottom: space.xxl },
  inner: { width: '100%', alignSelf: 'center', gap: space.xl },
  footer: { borderTopWidth: 1, paddingHorizontal: space.lg, paddingVertical: space.md },
  footerInner: { width: '100%', alignSelf: 'center', gap: space.sm },
  card: { borderRadius: radius.lg, borderWidth: 1, padding: space.lg, gap: space.sm },
  btn: {
    minHeight: TOUCH,
    maxWidth: '100%',
    borderRadius: radius.sm,
    borderWidth: 1,
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.sm,
  },
  btnBig: { minHeight: 68, borderRadius: radius.md, justifyContent: 'flex-start', paddingHorizontal: space.lg, gap: space.md },
  chip: {
    minHeight: 40,
    maxWidth: '100%',
    borderRadius: radius.sm,
    borderWidth: 1,
    paddingHorizontal: space.md,
    paddingVertical: 6,
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: space.xs,
  },
  radioDot: { width: 18, height: 18, borderRadius: radius.pill, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  radioInner: { width: 10, height: 10, borderRadius: radius.pill },
  box: { width: 24, height: 24, borderRadius: radius.sm, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  input: {
    minHeight: 48,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: space.md,
    fontFamily: font.regular,
    fontSize: size.md,
  },
  stepBtn: { width: TOUCH, height: TOUCH, borderRadius: radius.sm, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  overlay: { flex: 1, justifyContent: 'flex-end', alignItems: 'center' },
  sheet: {
    width: '100%',
    maxHeight: '88%',
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    borderWidth: 1,
    padding: space.lg,
    gap: space.md,
  },
});
