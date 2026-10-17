import { Tabs } from 'expo-router/js-tabs';

import { Icon } from '@/components/domain';
import { font, useTheme } from '@/theme';

export default function TabsLayout() {
  const { c } = useTheme();
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: c.bg },
        headerTitleStyle: { fontFamily: font.semibold, color: c.text },
        headerShadowVisible: false,
        tabBarActiveTintColor: c.accent,
        tabBarInactiveTintColor: c.muted,
        tabBarStyle: { backgroundColor: c.surface, borderTopColor: c.surfaceAlt, minHeight: 64 },
        tabBarLabelStyle: { fontFamily: font.medium, fontSize: 12 },
        tabBarItemStyle: { minHeight: 48, paddingVertical: 4 },
        sceneStyle: { backgroundColor: c.bg },
      }}>
      <Tabs.Screen
        name="index"
        options={{ title: 'Trang chủ', headerShown: false, tabBarIcon: ({ color }) => <Icon name="home" color={String(color)} /> }}
      />
      <Tabs.Screen name="kho" options={{ title: 'Kho', tabBarIcon: ({ color }) => <Icon name="box" color={String(color)} /> }} />
      <Tabs.Screen
        name="mam"
        options={{ title: 'Mâm cơm hôm nay', tabBarLabel: 'Mâm cơm', tabBarIcon: ({ color }) => <Icon name="tray" color={String(color)} /> }}
      />
      <Tabs.Screen
        name="di-cho"
        options={{ title: 'Danh sách đi chợ', tabBarLabel: 'Đi chợ', tabBarIcon: ({ color }) => <Icon name="cart" color={String(color)} /> }}
      />
      <Tabs.Screen name="nhat-ky" options={{ title: 'Nhật ký tuần', tabBarLabel: 'Nhật ký', tabBarIcon: ({ color }) => <Icon name="book" color={String(color)} /> }} />
    </Tabs>
  );
}
