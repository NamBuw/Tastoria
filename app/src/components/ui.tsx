import { type ReactNode } from 'react';
import {
  ActivityIndicator,
  Modal,
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

import { font, radius, size, space, TOUCH, useTheme } from '@/theme';

// ---- text ---------------------------------------------------------------------------------------

type Variant = 'body' | 'small' | 'label' | 'title' | 'h1' | 'h2' | 'huge';
const VARIANTS: Record<Variant, TextStyle> = {
  small: { fontSize: size.xs, lineHeight: 18, fontFamily: font.regular },
  body: { fontSize: size.sm, lineHeight: 22, fontFamily: font.regular },
  label: { fontSize: size.sm, lineHeight: 20, fontFamily: font.semibold },
  title: { fontSize: size.md, lineHeight: 24, fontFamily: font.semibold },
  h2: { fontSize: size.lg, lineHeight: 28, fontFamily: font.bold },
  h1: { fontSize: size.xl, lineHeight: 32, fontFamily: font.bold },
  huge: { fontSize: size.huge, lineHeight: 44, fontFamily: font.bold },
};

export function T({
  v = 'body',
  tone = 'text',
  style,
  ...p
}: TextProps & { v?: Variant; tone?: 'text' | 'muted' | 'accent' | 'danger' | 'onAccent' }) {
  const { c } = useTheme();
  return <Text {...p} style={[VARIANTS[v], { color: c[tone] }, style]} />;
}

// ---- layout -------------------------------------------------------------------------------------

export function Screen({
  children,
  scroll = true,
  footer,
  testID,
}: {
  children: ReactNode;
  scroll?: boolean;
  footer?: ReactNode;
  testID?: string;
}) {
  const { c } = useTheme();
  const inner = <View style={styles.inner}>{children}</View>;
  return (
    <SafeAreaView edges={['left', 'right', 'bottom']} style={{ flex: 1, backgroundColor: c.bg }} testID={testID}>
      {scroll ? (
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          {inner}
        </ScrollView>
      ) : (
        <View style={[styles.scroll, { flex: 1 }]}>{inner}</View>
      )}
      {footer ? (
        <View style={[styles.footer, { backgroundColor: c.bg, borderTopColor: c.surfaceAlt }]}>
          <View style={styles.footerInner}>{footer}</View>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

export function Card({ children, style, testID }: { children: ReactNode; style?: StyleProp<ViewStyle>; testID?: string }) {
  const { c } = useTheme();
  return (
    <View testID={testID} style={[styles.card, { backgroundColor: c.surface, borderColor: c.surfaceAlt }, style]}>{children}</View>
  );
}

export function Row({ children, style, gap = space.sm }: { children: ReactNode; style?: StyleProp<ViewStyle>; gap?: number }) {
  return <View style={[{ flexDirection: 'row', alignItems: 'center', gap, flexWrap: 'wrap' }, style]}>{children}</View>;
}

export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <View style={{ gap: space.sm }}>
      <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
        <T v="title" accessibilityRole="header" style={{ flexShrink: 1 }}>
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
  loading,
  disabled,
  icon,
  sub,
  testID,
  style,
  accessibilityLabel,
}: {
  label: string;
  onPress?: () => void;
  kind?: BtnKind;
  big?: boolean;
  loading?: boolean;
  disabled?: boolean;
  icon?: ReactNode;
  sub?: string;
  testID?: string;
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}) {
  const { c } = useTheme();
  const off = disabled || loading;
  const bg = kind === 'primary' ? c.accent : kind === 'danger' ? c.danger : kind === 'secondary' ? c.surface : 'transparent';
  const fg = kind === 'primary' || kind === 'danger' ? c.onAccent : c.accent;
  const border = kind === 'secondary' ? c.accent : 'transparent';
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
        { backgroundColor: bg, borderColor: border, opacity: off ? 0.55 : pressed ? 0.85 : 1 },
        style,
      ]}>
      {loading ? <ActivityIndicator color={fg} /> : icon}
      <View style={{ alignItems: big && icon ? 'flex-start' : 'center', flexShrink: 1 }}>
        <Text style={[big ? VARIANTS.h2 : VARIANTS.label, { color: fg, textAlign: 'center' }]}>{label}</Text>
        {sub ? <Text style={[VARIANTS.small, { color: fg }]}>{sub}</Text> : null}
      </View>
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
      <Text style={[VARIANTS.label, { color: c.accent, textDecorationLine: 'underline' }]}>{label}</Text>
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
          borderColor: selected ? c.accent : c.border,
          opacity: disabled ? 0.5 : pressed ? 0.85 : 1,
        },
      ]}>
      {selected ? <Text style={[VARIANTS.label, { color: c.accent }]}>✓</Text> : null}
      {left}
      <Text style={[VARIANTS.body, { color: c.text, flexShrink: 1 }]}>{label}</Text>
    </Pressable>
  );
}

export function Segmented<V extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: V; label: string }[];
  value: V | null | undefined;
  onChange: (v: V) => void;
  label?: string;
}) {
  return (
    <View style={{ gap: space.xs }} accessibilityRole="radiogroup" accessibilityLabel={label}>
      {label ? <T v="label">{label}</T> : null}
      <Row>
        {options.map((o) => (
          <Radio key={String(o.value)} label={o.label} selected={value === o.value} onPress={() => onChange(o.value)} />
        ))}
      </Row>
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
        { backgroundColor: selected ? c.accentSoft : c.surface, borderColor: selected ? c.accent : c.border },
      ]}>
      <View style={[styles.radioDot, { borderColor: selected ? c.accent : c.border }]}>
        {selected ? <View style={[styles.radioInner, { backgroundColor: c.accent }]} /> : null}
      </View>
      <Text style={[VARIANTS.body, { color: c.text }]}>{label}</Text>
    </Pressable>
  );
}

export function Checkbox({
  checked,
  onChange,
  label,
  sub,
  testID,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  sub?: ReactNode;
  testID?: string;
}) {
  const { c } = useTheme();
  return (
    <Pressable
      testID={testID}
      onPress={() => onChange(!checked)}
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      style={{ flexDirection: 'row', gap: space.md, minHeight: TOUCH, alignItems: 'flex-start', paddingVertical: space.sm }}>
      <View
        style={[
          styles.box,
          { borderColor: checked ? c.accent : c.border, backgroundColor: checked ? c.accent : 'transparent' },
        ]}>
        {checked ? <Text style={{ color: c.onAccent, fontFamily: font.bold, fontSize: 16 }}>✓</Text> : null}
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
  return (
    <View style={{ gap: space.xs }}>
      <T v="label">{label}</T>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={c.muted}
        {...p}
        style={[
          styles.input,
          { borderColor: error ? c.danger : c.border, color: c.text, backgroundColor: c.surface },
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
  const btn = (txt: string, next: number, a11y: string) => (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={a11y}
      disabled={next < min || next > max}
      onPress={() => onChange(next)}
      testID={testID ? `${testID}-${txt === '+' ? 'plus' : 'minus'}` : undefined}
      style={({ pressed }) => [
        styles.stepBtn,
        { borderColor: c.border, backgroundColor: c.surface, opacity: next < min || next > max ? 0.4 : pressed ? 0.8 : 1 },
      ]}>
      <Text style={[VARIANTS.h2, { color: c.accent }]}>{txt}</Text>
    </Pressable>
  );
  return (
    <View style={{ gap: space.xs }}>
      <T v="label">{label}</T>
      <Row gap={space.md} style={{ flexWrap: 'nowrap' }}>
        {btn('−', value - step, `Giảm ${label.toLowerCase()}`)}
        <T v="h2" style={{ minWidth: 64, textAlign: 'center' }} accessibilityLiveRegion="polite">
          {format ? format(value) : value}
        </T>
        {btn('+', value + step, `Tăng ${label.toLowerCase()}`)}
      </Row>
    </View>
  );
}

// ---- states -------------------------------------------------------------------------------------

export function Loading({ label = 'Đang tải…' }: { label?: string }) {
  const { c } = useTheme();
  return (
    <View style={{ padding: space.xl, alignItems: 'center', gap: space.sm }} accessibilityLiveRegion="polite">
      <ActivityIndicator color={c.accent} />
      <T tone="muted">{label}</T>
    </View>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { c } = useTheme();
  return (
    <View
      accessibilityRole="alert"
      style={[styles.card, { backgroundColor: c.dangerSoft, borderColor: c.danger, gap: space.sm }]}>
      <T>{message}</T>
      {onRetry ? <Button kind="secondary" label="Thử lại" onPress={onRetry} /> : null}
    </View>
  );
}

export function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'ok' | 'warn' }) {
  const { c } = useTheme();
  const bg = tone === 'ok' ? c.okSoft : tone === 'warn' ? c.dangerSoft : c.surfaceAlt;
  return <View style={[styles.card, { backgroundColor: bg, borderColor: 'transparent', gap: space.xs }]}>{children}</View>;
}

export function Empty({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <Card style={{ alignItems: 'flex-start', gap: space.sm }}>
      <T v="title">{title}</T>
      {body ? <T tone="muted">{body}</T> : null}
      {action}
    </Card>
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
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={[styles.overlay, { backgroundColor: c.overlay }]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Đóng" />
        <View
          testID={testID}
          accessibilityViewIsModal
          style={[styles.sheet, { backgroundColor: c.bg, borderColor: c.surfaceAlt }]}>
          <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
            <T v="h2" accessibilityRole="header" style={{ flexShrink: 1 }}>
              {title}
            </T>
            <Pressable
              onPress={onClose}
              accessibilityRole="button"
              accessibilityLabel="Đóng"
              style={{ minWidth: TOUCH, minHeight: TOUCH, alignItems: 'center', justifyContent: 'center' }}>
              <Text style={[VARIANTS.h2, { color: c.muted }]}>×</Text>
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
        Bước {step}/{total} · {label}
      </T>
      <View style={{ flexDirection: 'row', gap: 6 }}>
        {Array.from({ length: total }, (_, i) => (
          <View
            key={i}
            style={{ flex: 1, height: 6, borderRadius: 3, backgroundColor: i < step ? c.accent : c.surfaceAlt }}
          />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { flexGrow: 1, paddingHorizontal: space.lg, paddingVertical: space.lg },
  inner: { width: '100%', maxWidth: 560, alignSelf: 'center', gap: space.lg },
  footer: { borderTopWidth: StyleSheet.hairlineWidth, paddingHorizontal: space.lg, paddingVertical: space.md },
  footerInner: { width: '100%', maxWidth: 560, alignSelf: 'center', gap: space.sm },
  card: { borderRadius: radius.md, borderWidth: 1, padding: space.lg, gap: space.sm },
  btn: {
    minHeight: TOUCH,
    borderRadius: radius.pill,
    borderWidth: 1.5,
    paddingHorizontal: space.xl,
    paddingVertical: space.sm,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.sm,
  },
  btnBig: { minHeight: 72, borderRadius: radius.lg, justifyContent: 'flex-start', paddingHorizontal: space.lg },
  chip: {
    minHeight: TOUCH,
    borderRadius: radius.pill,
    borderWidth: 1,
    paddingHorizontal: space.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
  },
  radioDot: { width: 20, height: 20, borderRadius: 10, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  radioInner: { width: 10, height: 10, borderRadius: 5 },
  box: { width: 26, height: 26, borderRadius: 6, borderWidth: 2, alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  input: {
    minHeight: TOUCH,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: space.md,
    fontFamily: font.regular,
    fontSize: size.md,
  },
  stepBtn: { width: TOUCH, height: TOUCH, borderRadius: TOUCH / 2, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  overlay: { flex: 1, justifyContent: 'flex-end', alignItems: 'center' },
  sheet: {
    width: '100%',
    maxWidth: 560,
    maxHeight: '88%',
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    borderWidth: 1,
    padding: space.lg,
    gap: space.md,
  },
});
