import { Image } from 'expo-image';
import { type ReactNode, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, TextInput, View, useWindowDimensions, type TextInputProps } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { font, useTheme } from '@/theme';
import { SLOGAN, TrayMark } from './Brand';
import { T } from './ui';

export function AuthShell({ children, title, subtitle, testID }: { children: ReactNode; title: string; subtitle: string; testID: string }) {
  const { c } = useTheme();
  const { width } = useWindowDimensions();
  const wide = width >= 960;
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }} testID={testID}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ flexGrow: 1 }}>
          <View style={[styles.layout, { flexDirection: wide ? 'row' : 'column', padding: wide ? 24 : 0 }]}>
            {wide ? <View style={styles.editorial}>
              <View style={styles.editorialCopy}>
                <T style={styles.kicker}>MỘT CHÚT QUEN. MỘT CHÚT MỚI.</T>
                <T accessibilityRole="header" style={styles.headline}>Bữa ngon,{'\n'}chuyện còn dài.</T>
                <T style={styles.caption}>Từ căn bếp nhỏ đến những điều đáng nhớ.</T>
              </View>
              <Image source={require('../../assets/food/vietnamese-table.jpg')} contentFit="cover" style={styles.photo}
                accessibilityLabel="Mâm cơm Việt với bún, nem và rau thơm, ảnh chụp của Jakub Kapusnak" />
              <View style={styles.photoNote}><T style={{ color: '#26291E', fontSize: 12 }}>{SLOGAN}</T><T style={{ color: '#26291E' }}>↗</T></View>
            </View> : null}
            <View style={[styles.formSide, { paddingHorizontal: wide ? 48 : 24, paddingVertical: wide ? 32 : 24 }]}>
              <View style={styles.formWidth}>
                <View style={styles.brand}><TrayMark size={38} /><T style={{ fontFamily: font.bold, fontSize: 30, lineHeight: 40, letterSpacing: -1 }}>tastoria<T style={{ color: c.accent, fontSize: 30 }}>.</T></T></View>
                <View style={{ marginTop: wide ? 52 : 36, marginBottom: 28, gap: 12 }}>
                  <T accessibilityRole="header" style={{ fontFamily: font.bold, fontSize: wide ? 38 : 32, lineHeight: wide ? 48 : 42, letterSpacing: -1 }}>{title}</T>
                  <T tone="muted" style={{ fontSize: 14, lineHeight: 23 }}>{subtitle}</T>
                </View>
                <View style={{ gap: 20 }}>{children}</View>
                <View style={{ marginTop: 32, paddingTop: 18, borderTopWidth: 1, borderTopColor: c.hairline }}>{Platform.OS === 'web' ? <AuthLink label="← Về trang giới thiệu Tastoria" muted onPress={() => window.location.assign('/')} /> : null}{!wide ? <T v="small" tone="muted" style={{ marginTop: 12 }}>{SLOGAN}</T> : null}</View>
              </View>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export function AuthLink({ label, onPress, testID, muted = false }: { label: string; onPress: () => void; testID?: string; muted?: boolean }) {
  return <Pressable accessibilityRole="link" onPress={onPress} testID={testID} style={({ pressed }) => ({ minHeight: 44, justifyContent: 'center', opacity: pressed ? .6 : 1 })}><T v="label" tone={muted ? 'muted' : 'accent'} style={{ fontSize: 13 }}>{label}</T></Pressable>;
}

export function AuthField({ label, error, hint, secureTextEntry, ...props }: TextInputProps & { label: string; error?: string; hint?: string }) {
  const { c } = useTheme();
  const [focus, setFocus] = useState(false);
  const [show, setShow] = useState(false);
  return <View style={{ gap: 8 }}>
    <T v="label" style={{ fontSize: 13 }}>{label}</T>
    <View style={{ flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: 12, borderColor: error ? c.danger : focus ? c.accent : c.border, backgroundColor: c.surface }}>
      <TextInput {...props} accessibilityLabel={label} secureTextEntry={secureTextEntry && !show} onFocus={() => setFocus(true)} onBlur={() => setFocus(false)} placeholderTextColor={c.muted}
        style={{ flex: 1, minWidth: 0, minHeight: 56, paddingHorizontal: 16, fontSize: 16, fontFamily: font.regular, color: c.text, borderRadius: 12 }} />
      {secureTextEntry ? <Pressable accessibilityRole="button" accessibilityLabel={show ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'} onPress={() => setShow(!show)} style={{ minWidth: 54, minHeight: 48, alignItems: 'center', justifyContent: 'center' }}><T v="small" tone="accent">{show ? 'Ẩn' : 'Hiện'}</T></Pressable> : null}
    </View>
    {error ? <T v="small" tone="danger" accessibilityLiveRegion="polite">{error}</T> : hint ? <T v="small" tone="muted">{hint}</T> : null}
  </View>;
}

const styles = StyleSheet.create({
  layout: { flex: 1, width: '100%', maxWidth: 1600, alignSelf: 'center' },
  editorial: { width: '48%', backgroundColor: '#F3512C', borderRadius: 24, overflow: 'hidden', minHeight: 720 },
  editorialCopy: { padding: 40, paddingBottom: 36 },
  kicker: { color: '#26291E', fontSize: 10, letterSpacing: 1.7, fontFamily: font.semibold },
  headline: { color: '#26291E', fontSize: 52, lineHeight: 63, letterSpacing: -2, fontFamily: font.bold, marginTop: 30 },
  caption: { color: '#26291E', fontSize: 14, lineHeight: 24, marginTop: 20 },
  photo: { width: '100%', flex: 1, minHeight: 300 },
  photoNote: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 32, paddingVertical: 18, backgroundColor: '#DCEB91' },
  formSide: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  formWidth: { width: '100%', maxWidth: 400 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 10 },
});
