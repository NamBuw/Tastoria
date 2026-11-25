import { Image } from 'expo-image';
import { type ReactNode, useId, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
  type TextInputProps,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { font, radius, size, space, TOUCH, useLayout, useTheme } from '@/theme';

import { FOOD_PHOTOS, SLOGAN, Wordmark } from './Brand';
import { Icon } from './domain';
import { T } from './ui';

export function AuthShell({
  children,
  title,
  subtitle,
  testID,
}: {
  children: ReactNode;
  title: string;
  subtitle: string;
  testID: string;
}) {
  const { c } = useTheme();
  const { isWide } = useLayout();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: 'transparent' }} testID={testID}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ flexGrow: 1 }}>
          <View style={[styles.layout, { flexDirection: isWide ? 'row' : 'column', padding: isWide ? space.xl : 0 }]}>
            {isWide ? (
              <View
                testID="auth-editorial"
                style={[
                  styles.editorial,
                  { backgroundColor: c.editorialSurface, borderColor: c.hairline },
                ]}>
                <Image
                  source={FOOD_PHOTOS.table}
                  contentFit="cover"
                  style={styles.photo}
                  accessibilityLabel="Mâm cơm Việt với bún, nem và rau thơm"
                />
                <View style={[styles.editorialCopy, { backgroundColor: c.editorialSurface, borderTopWidth: 1, borderTopColor: c.hairline }]}>
                  <T style={[styles.headline, { color: c.onEditorial }]}>
                    Tối nay nấu gì từ đồ{'\n'}còn trong tủ lạnh?
                  </T>
                  <T style={[styles.caption, { color: c.onStoryMuted }]}>
                    Chụp món tính calo, quản lý tủ lạnh và gợi ý món nấu nhanh từ đồ sẵn có.
                  </T>
                </View>
              </View>
            ) : null}

            <View style={[styles.formSide, { paddingHorizontal: isWide ? 48 : 24, paddingVertical: isWide ? 32 : 24 }]}>
              <View
                style={[
                  styles.formCard,
                  {
                    backgroundColor: c.surfaceCard,
                    borderColor: c.hairline,
                    borderWidth: 1,
                    borderRadius: radius.lg,
                    padding: isWide ? 40 : 24,
                  },
                ]}>
                <View style={{ paddingBottom: space.md, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
                  <Wordmark size="lg" masthead subtitle={SLOGAN} />
                </View>

                <View style={{ marginTop: 24, marginBottom: 20, gap: 8 }}>
                  <T v="h1" accessibilityRole="header" style={{ fontSize: size.display, lineHeight: 36, letterSpacing: -0.6 }}>
                    {title}
                  </T>
                  <T tone="muted" style={{ fontSize: size.md, lineHeight: 24 }}>
                    {subtitle}
                  </T>
                </View>

                <View style={{ gap: 16 }}>{children}</View>

                <View style={{ marginTop: 28, paddingTop: 16, borderTopWidth: 1, borderTopColor: c.hairline }}>
                  {Platform.OS === 'web' ? (
                    <AuthLink
                      label="Về trang giới thiệu Mỹ Vị"
                      left={<Icon name="arrow-left" size={16} color={c.muted} />}
                      muted
                      onPress={() => window.location.assign('/')}
                    />
                  ) : null}
                  {!isWide ? (
                    <T v="small" tone="muted" style={{ marginTop: 8 }}>
                      {SLOGAN}
                    </T>
                  ) : null}
                </View>
              </View>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export function AuthLink({
  label,
  onPress,
  testID,
  muted = false,
  left,
}: {
  label: string;
  onPress: () => void;
  testID?: string;
  muted?: boolean;
  left?: ReactNode;
}) {
  return (
    <Pressable
      accessibilityRole="link"
      accessibilityLabel={label}
      onPress={onPress}
      testID={testID}
      style={({ pressed }) => ({
        minHeight: TOUCH,
        flexDirection: 'row',
        alignItems: 'center',
        gap: space.xs,
        opacity: pressed ? 0.65 : 1,
      })}>
      {left}
      <T v="label" tone={muted ? 'muted' : 'accent'}>
        {label}
      </T>
    </Pressable>
  );
}

export function AuthField({
  label,
  error,
  hint,
  secureTextEntry,
  ...props
}: TextInputProps & { label: string; error?: string; hint?: string }) {
  const { c } = useTheme();
  const labelId = useId();
  const [focus, setFocus] = useState(false);
  const [show, setShow] = useState(false);
  return (
    <View style={{ gap: 6 }}>
      <T v="label" nativeID={labelId}>
        {label}
      </T>
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          borderWidth: 1,
          borderRadius: radius.md,
          borderColor: error ? c.danger : focus ? c.accent : c.border,
          backgroundColor: c.bg,
        }}>
        <TextInput
          {...props}
          accessibilityLabel={label}
          aria-labelledby={labelId}
          secureTextEntry={secureTextEntry && !show}
          onFocus={() => setFocus(true)}
          onBlur={() => setFocus(false)}
          placeholderTextColor={c.muted}
          style={{
            flex: 1,
            minWidth: 0,
            minHeight: 50,
            paddingHorizontal: 16,
            fontSize: 16,
            fontFamily: font.regular,
            color: c.text,
            borderRadius: radius.md,
          }}
        />
        {secureTextEntry ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={show ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
            onPress={() => setShow(!show)}
            style={{ minWidth: TOUCH, minHeight: TOUCH, alignItems: 'center', justifyContent: 'center', marginRight: 4 }}>
            <Icon name={show ? 'eye-off' : 'eye'} size={20} color={c.muted} />
          </Pressable>
        ) : null}
      </View>
      {error ? (
        <T v="small" tone="danger" accessibilityLiveRegion="polite">
          {error}
        </T>
      ) : hint ? (
        <T v="small" tone="muted">
          {hint}
        </T>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  layout: { flex: 1, width: '100%', maxWidth: 1360, alignSelf: 'center', gap: space.xl },
  editorial: {
    flex: 1,
    borderRadius: radius.lg,
    overflow: 'hidden',
    minHeight: 680,
    borderWidth: 1,
  },
  photo: { width: '100%', flex: 1, minHeight: 360 },
  editorialCopy: { padding: 36, gap: 14 },
  headline: { fontSize: size.huge, lineHeight: 40, letterSpacing: -0.6, fontFamily: font.displayMedium, marginTop: 4 },
  caption: { fontSize: size.md, lineHeight: 24 },
  formSide: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  formCard: { width: '100%', maxWidth: 460, borderRadius: radius.lg, borderWidth: 1 },
});
