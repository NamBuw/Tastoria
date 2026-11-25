import { BottomTabBar, Tabs } from 'expo-router/js-tabs';
import { Text, useWindowDimensions, View } from 'react-native';

import { Icon, type IconName } from '@/components/domain';
import { font, radius, useTheme, type Palette } from '@/theme';

/** Tab icon with a refined rounded badge when the tab is active. */
function tabIcon(name: IconName, c: Palette, isPrimary?: boolean) {
  function TabIcon({ color, focused }: { color: unknown; focused: boolean }) {
    if (isPrimary) {
      return (
        <View
          style={{
            width: 52,
            height: 32,
            borderRadius: radius.pill,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: focused ? c.accentDisplay : c.accent,
          }}>
          <Icon name={name} color={c.onAccent} size={20} />
        </View>
      );
    }
    return (
      <View
        style={{
          width: 48,
          height: 26,
          borderRadius: radius.pill,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: focused ? c.accentSoft : 'transparent',
        }}>
        <Icon name={name} color={String(color)} size={20} />
      </View>
    );
  }
  return TabIcon;
}

export default function TabsLayout() {
  const { c } = useTheme();
  const { width } = useWindowDimensions();
  const hideBar = width >= 768;
  return (
    <Tabs
      tabBar={(props) =>
        hideBar ? null : (
          <View testID="mobile-bottom-tabs">
            <BottomTabBar {...props} />
          </View>
        )
      }
      screenOptions={{
        headerStyle: { backgroundColor: c.surface },
        headerTitleStyle: { fontFamily: font.semibold, color: c.text, fontSize: 18 },
        headerShadowVisible: false,
        tabBarActiveTintColor: c.accent,
        tabBarInactiveTintColor: c.muted,
        tabBarAllowFontScaling: true,
        tabBarStyle: { backgroundColor: c.surfaceCard, borderTopColor: c.hairline, borderTopWidth: 1, height: 78, paddingTop: 8, paddingBottom: 12 },
        tabBarLabelStyle: { fontFamily: font.semibold, fontSize: 12, marginTop: 1 },
        tabBarLabel: ({ children, color }) => (
          <Text
            allowFontScaling
            maxFontSizeMultiplier={1.2}
            style={{ fontFamily: font.semibold, fontSize: 12, lineHeight: 16, color, textAlign: 'center', marginTop: 1 }}>
            {children}
          </Text>
        ),
        tabBarItemStyle: { minHeight: 52, paddingVertical: 2 },
        sceneStyle: { backgroundColor: 'transparent' },
      }}>
      <Tabs.Screen
        name="bep"
        options={{ title: 'Hôm nay', headerShown: false, tabBarLabel: 'Hôm nay', tabBarIcon: tabIcon('home', c) }}
      />
      <Tabs.Screen
        name="mam"
        options={{ title: 'Nấu ăn', headerShown: false, tabBarLabel: 'Nấu ăn', tabBarIcon: tabIcon('tray', c) }}
      />
      <Tabs.Screen
        name="quet-tab"
        options={{ title: 'Quét & Ghi', headerShown: false, tabBarLabel: 'Quét', tabBarIcon: tabIcon('camera', c, true) }}
      />
      <Tabs.Screen
        name="kho"
        options={{ title: 'Tủ lạnh', headerShown: false, tabBarLabel: 'Tủ lạnh', tabBarIcon: tabIcon('box', c) }}
      />
      <Tabs.Screen
        name="nhat-ky"
        options={{ title: 'Nhật ký ăn uống', headerShown: false, tabBarLabel: 'Nhật ký', tabBarIcon: tabIcon('book', c) }}
      />
      <Tabs.Screen
        name="di-cho"
        options={{ href: null, title: 'Đi chợ', headerShown: false, tabBarIcon: tabIcon('cart', c) }}
      />
    </Tabs>
  );
}
