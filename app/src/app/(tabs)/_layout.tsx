import { Tabs } from 'expo-router/js-tabs';
import { View } from 'react-native';

import { Icon } from '@/components/domain';
import { font, useTheme, type Palette } from '@/theme';

/** Tab icon with a soft pill behind it when the tab is active. */
function tabIcon(name: Parameters<typeof Icon>[0]['name'], c: Palette) {
  function TabIcon({ color, focused }: { color: unknown; focused: boolean }) {
    return (
      <View style={{ width: 56, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center', backgroundColor: focused ? c.accentSoft : 'transparent' }}>
        <Icon name={name} color={String(color)} size={22} />
      </View>
    );
  }
  return TabIcon;
}

export default function TabsLayout() {
  const { c } = useTheme();
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: c.bg },
        headerTitleStyle: { fontFamily: font.bold, color: c.text, fontSize: 19 },
        headerShadowVisible: false,
        tabBarActiveTintColor: c.accent,
        tabBarInactiveTintColor: c.muted,
        tabBarStyle: { backgroundColor: c.surface, borderTopColor: c.hairline, minHeight: 68, paddingTop: 6 },
        tabBarLabelStyle: { fontFamily: font.semibold, fontSize: 12, marginTop: 2 },
        tabBarItemStyle: { minHeight: 48, paddingVertical: 4 },
        sceneStyle: { backgroundColor: c.bg },
      }}>
      <Tabs.Screen
        name="bep"
        options={{ title: 'Bếp nhà', headerShown: false, tabBarIcon: tabIcon('home', c) }}
      />
      <Tabs.Screen name="kho" options={{ title: 'Kho bếp', tabBarIcon: tabIcon('box', c) }} />
      <Tabs.Screen
        name="mam"
        options={{ title: 'Mâm cơm hôm nay', tabBarLabel: 'Mâm cơm', tabBarIcon: tabIcon('tray', c) }}
      />
      <Tabs.Screen
        name="di-cho"
        options={{ title: 'Danh sách đi chợ', tabBarLabel: 'Đi chợ', tabBarIcon: tabIcon('cart', c) }}
      />
      <Tabs.Screen name="nhat-ky" options={{ title: 'Chuyện bếp của bạn', tabBarLabel: 'Nhật ký', tabBarIcon: tabIcon('book', c) }} />
    </Tabs>
  );
}
