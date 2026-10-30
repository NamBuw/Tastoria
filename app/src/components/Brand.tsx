import { Image } from 'expo-image';
import { Platform, View } from 'react-native';
import Svg, { Circle } from 'react-native-svg';

import { radius, space, useTheme } from '@/theme';

import { LinkButton, T } from './ui';

export const SLOGAN = 'Taste and write your story';

/** App mark: round tray seen from above, rice bowl in the centre and three dishes. */
export function TrayMark({ size = 56 }: { size?: number }) {
  const { c } = useTheme();
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64" accessibilityElementsHidden importantForAccessibility="no">
      <Circle cx="32" cy="32" r="31" fill={c.trayRim} />
      <Circle cx="32" cy="32" r="28.5" fill={c.tray} />
      <Circle cx="32" cy="32" r="8" fill={c.rice} stroke={c.glaze} strokeWidth="1.5" />
      <Circle cx="32" cy="14.5" r="8" fill={c.dish} stroke={c.glaze} strokeWidth="2" />
      <Circle cx="32" cy="14.5" r="4.5" fill="#B06A35" />
      <Circle cx="16.8" cy="40.8" r="8" fill={c.dish} stroke={c.glaze} strokeWidth="2" />
      <Circle cx="16.8" cy="40.8" r="4.5" fill={c.herb} />
      <Circle cx="47.2" cy="40.8" r="8" fill={c.dish} stroke={c.glaze} strokeWidth="2" />
      <Circle cx="47.2" cy="40.8" r="5" fill="#D9B45A" />
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
