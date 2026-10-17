import { View } from 'react-native';
import Svg, { Circle } from 'react-native-svg';

import { space, useTheme } from '@/theme';

import { T } from './ui';

/** App mark: round tray seen from above, rice bowl in the centre and three dishes. */
export function TrayMark({ size = 56 }: { size?: number }) {
  const { c } = useTheme();
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64" accessibilityElementsHidden importantForAccessibility="no">
      <Circle cx="32" cy="32" r="30" fill={c.tray} stroke={c.trayRim} strokeWidth="3" />
      <Circle cx="32" cy="32" r="8" fill={c.rice} stroke={c.trayRim} strokeWidth="1.5" />
      <Circle cx="32" cy="14" r="7.5" fill={c.dish} stroke={c.accent} strokeWidth="2" />
      <Circle cx="16.5" cy="41" r="7.5" fill={c.dish} stroke={c.accent} strokeWidth="2" />
      <Circle cx="47.5" cy="41" r="7.5" fill={c.dish} stroke={c.accent} strokeWidth="2" />
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
        {subtitle ? <T tone="muted">{subtitle}</T> : null}
      </View>
    </View>
  );
}
