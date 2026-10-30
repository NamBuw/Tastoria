import { Image } from 'expo-image';
import { Platform, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { radius, space, useTheme } from '@/theme';

import { LinkButton, T } from './ui';

export const SLOGAN = 'Taste and write your story';

/** Tastoria's own mark: a bowl and two rising strokes of steam. */
export function TrayMark({ size = 56 }: { size?: number }) {
  const { c } = useTheme();
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64" accessibilityElementsHidden importantForAccessibility="no">
      <Path d="M9 30h46c-1 14-11 24-23 24S10 44 9 30Z" fill={c.accent} />
      <Path d="M18 59h28" stroke={c.text} strokeWidth="5" strokeLinecap="round" />
      <Path d="M25 8c-9 8 7 9-1 17M40 5c-9 8 7 10-1 17" fill="none" stroke={c.text} strokeWidth="5" strokeLinecap="round" />
      <Path d="M16 36h32" stroke={c.surface} strokeWidth="3" strokeLinecap="round" />
    </Svg>
  );
}

export function BrandHeader({ subtitle }: { subtitle?: string }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: space.md, marginTop: space.lg }}>
      <TrayMark />
      <View style={{ flexShrink: 1 }}>
        <T v="h1" accessibilityRole="header">
          Tastoria
        </T>
        <T v="small" tone="accent">{SLOGAN}</T>
        {subtitle ? <T v="small" tone="muted">{subtitle}</T> : null}
      </View>
    </View>
  );
}

/** Editorial image only; never presented as the user's generated meal. */
export function FoodStory({ compact = false }: { compact?: boolean }) {
  const { c } = useTheme();
  return (
    <View style={{ borderRadius: radius.lg, overflow: 'hidden', backgroundColor: c.surface, borderWidth: 1, borderColor: c.hairline }}>
      <Image source={require('../../assets/food/vietnamese-table.jpg')} contentFit="cover"
        accessibilityLabel="Bữa ăn Việt quây quần với bún, nem, thịt nướng và rau thơm"
        style={{ width: '100%', height: compact ? 150 : 210 }} />
      <View style={{ padding: space.lg, gap: space.sm }}>
        <T v="small" tone="herb" style={{ letterSpacing: 2 }}>TỪ CĂN BẾP CỦA BẠN</T>
        <T v={compact ? 'h2' : 'huge'} accessibilityRole="header">Mỗi bữa ngon,{'\n'}một câu chuyện.</T>
        <T tone="muted">Từ những nguyên liệu quen thuộc, nấu một mâm cơm và lưu lại hành trình vào bếp của bạn.</T>
      </View>
    </View>
  );
}

/** Leave the app entirely so the public website never starts an auth redirect. */
export function PublicHomeLink() {
  if (Platform.OS !== 'web') return null;
  return <LinkButton label="← Về trang giới thiệu Tastoria" onPress={() => window.location.assign('/')} />;
}
