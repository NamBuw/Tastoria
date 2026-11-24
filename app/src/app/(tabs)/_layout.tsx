import { BottomTabBar, Tabs } from 'expo-router/js-tabs';
import { Text, useWindowDimensions, View } from 'react-native';

import { Icon, type IconName } from '@/components/domain';
import { font, radius, useTheme, type Palette } from '@/theme';

/** Tab icon with a refined rounded badge when the tab is active. */
function tabIcon(name: IconName, c: Palette) {
  function TabIcon({ color, focused }: { color: unknown; focused: boolean }) {
    return (
      <View
        style={{
          width: 48,
          height: 24,
          borderRadius: radius.sm,
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
        tabBarStyle: { backgroundColor: c.surfaceCard, borderTopColor: c.border, borderTopWidth: 1.5, height: 78, paddingTop: 8, paddingBottom: 12 },
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
        options={{ title: 'Bếp nhà', headerShown: false, tabBarIcon: tabIcon('home', c) }}
      />
      <Tabs.Screen name="kho" options={{ title: 'Kho bếp', headerShown: false, tabBarIcon: tabIcon('box', c) }} />
      <Tabs.Screen
        name="mam"
        options={{ title: 'Mâm cơm hôm nay', headerShown: false, tabBarLabel: 'Mâm cơm', tabBarIcon: tabIcon('tray', c) }}
      />
      <Tabs.Screen
        name="di-cho"
        options={{ title: 'Danh sách đi chợ', headerShown: false, tabBarLabel: 'Đi chợ', tabBarIcon: tabIcon('cart', c) }}
      />
      <Tabs.Screen
        name="nhat-ky"
        options={{ title: 'Nhật ký bữa ăn', headerShown: false, tabBarLabel: 'Nhật ký', tabBarIcon: tabIcon('book', c) }}
      />
    </Tabs>
  );
}
