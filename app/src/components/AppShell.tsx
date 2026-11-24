import { type Href, usePathname, useRouter, useSegments } from 'expo-router';
import { type ReactNode } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { useSession } from '@/auth/session';
import { BroadsheetCrest, VermilionSeal, Wordmark } from '@/components/Brand';
import { Icon, type IconName } from '@/components/domain';
import { T } from '@/components/ui';
import { radius, space, TOUCH, useLayout, useTheme } from '@/theme';

type NavItem = {
  key: string;
  href: string;
  label: string;
  icon: IconName;
  testID: string;
};

const PRIMARY_NAV: NavItem[] = [
  { key: 'bep', href: '/bep', label: 'Bếp nhà', icon: 'home', testID: 'sidebar-nav-bep' },
  { key: 'quet', href: '/quet', label: 'Quét & Calo', icon: 'camera', testID: 'sidebar-nav-quet' },
  { key: 'mam', href: '/mam', label: 'Mâm cơm', icon: 'tray', testID: 'sidebar-nav-mam' },
  { key: 'kho', href: '/kho', label: 'Kho bếp', icon: 'box', testID: 'sidebar-nav-kho' },
  { key: 'nhat-ky', href: '/nhat-ky', label: 'Nhật ký', icon: 'book', testID: 'sidebar-nav-nhat-ky' },
];

export function maskEmail(email: string): string {
  const at = email.indexOf('@');
  if (at <= 0) return '***';
  const local = email.slice(0, at);
  const domain = email.slice(at + 1);
  const prefix = local.slice(0, Math.min(2, local.length));
  return `${prefix}***@${domain}`;
}

export function AppShell({ children }: { children: ReactNode }) {
  const { c } = useTheme();
  const { status, user, signOut } = useSession();
  const segments = useSegments();
  const pathname = usePathname();
  const router = useRouter();
  const { isMobile, isDesktop } = useLayout();

  const first = segments.find((s) => !s.startsWith('(')) ?? '';
  const suppressed =
    status !== 'signedIn' ||
    ['dang-nhap', 'dang-ky', 'quen-mat-khau', 'dat-lai-mat-khau', 'onboarding'].includes(first) ||
    (first === 'khao-sat' && status !== 'signedIn');

  if (suppressed || isMobile) {
    return <>{children}</>;
  }

  const isStaff = user?.role === 'admin' || user?.role === 'ml_operator';
  const utilityIcons: NavItem[] = [
    { key: 'di-cho', href: '/di-cho', label: 'Đi chợ', icon: 'cart', testID: 'sidebar-nav-di-cho' },
    ...(isStaff
      ? [{ key: 'quan-tri', href: '/quan-tri', label: 'Quản trị', icon: 'shield' as const, testID: 'sidebar-nav-quan-tri' }]
      : []),
    { key: 'cai-dat', href: '/cai-dat', label: 'Cài đặt', icon: 'gear', testID: 'sidebar-nav-cai-dat' },
  ];

  const activeKey = pathname.startsWith('/mon') || pathname.startsWith('/kham-pha')
    ? 'mam'
    : pathname.startsWith('/nau')
      ? 'mam'
      : pathname.startsWith('/quet')
        ? 'quet'
        : first || 'bep';

  const renderPrimaryItem = (item: NavItem) => {
    const active = activeKey === item.key;
    return (
      <Pressable
        key={item.key}
        testID={item.testID}
        accessibilityRole="button"
        accessibilityLabel={item.label}
        accessibilityState={{ selected: active }}
        onPress={() => router.push(item.href as Href)}
        style={({ pressed }) => [
          isDesktop ? styles.desktopItem : styles.tabletItem,
          {
            backgroundColor: active ? c.accentSoft : pressed ? c.surfaceAlt : 'transparent',
            borderLeftWidth: isDesktop ? 3 : 0,
            borderLeftColor: active ? c.accent : 'transparent',
          },
        ]}>
        <Icon name={item.icon} size={20} color={active ? c.accent : c.muted} />
        {isDesktop ? (
          <T
            v={active ? 'label' : 'body'}
            style={{
              color: active ? c.accent : c.text,
              flexShrink: 1,
            }}>
            {item.label}
          </T>
        ) : null}
      </Pressable>
    );
  };

  const renderUtilityIcon = (item: NavItem) => {
    const active = activeKey === item.key;
    return (
      <Pressable
        key={item.key}
        testID={item.testID}
        accessibilityRole="button"
        accessibilityLabel={item.label}
        accessibilityState={{ selected: active }}
        onPress={() => router.push(item.href as Href)}
        style={({ pressed }) => [
          styles.utilityIconBtn,
          {
            backgroundColor: active ? c.accentSoft : pressed ? c.surfaceAlt : 'transparent',
            borderColor: active ? c.accent : c.hairline,
          },
        ]}>
        <Icon name={item.icon} size={18} color={active ? c.accent : c.muted} />
      </Pressable>
    );
  };

  return (
    <View style={{ flex: 1, flexDirection: 'row', backgroundColor: 'transparent' }}>
      <View
        testID={isDesktop ? 'desktop-sidebar-rail' : 'tablet-rail'}
        accessibilityRole="none"
        style={[
          isDesktop ? styles.desktopRail : styles.tabletRail,
          {
            backgroundColor: c.surfaceCard,
            borderRightColor: c.border,
          },
        ]}>
        <View style={[styles.brandRowWrap, !isDesktop && { alignItems: 'center', paddingHorizontal: 0 }]}>
          <View style={[styles.brandRow, { borderBottomColor: c.border }, !isDesktop && { justifyContent: 'center', paddingHorizontal: 0 }]}>
            {isDesktop ? (
              <View style={{ gap: space.xs }}>
                <Wordmark size="md" masthead />
                <VermilionSeal />
              </View>
            ) : (
              <BroadsheetCrest size="sm" />
            )}
          </View>
          <View style={{ height: 1, backgroundColor: c.hairline, marginTop: 2 }} />
        </View>

        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={[styles.navList, !isDesktop && { alignItems: 'center', paddingHorizontal: 0 }]}
          showsVerticalScrollIndicator={false}>
          {PRIMARY_NAV.map(renderPrimaryItem)}
        </ScrollView>

        <View style={[styles.railFooter, { borderTopColor: c.hairline }, !isDesktop && { alignItems: 'center', paddingHorizontal: space.xs }]}>
          <View style={[styles.utilityRow, !isDesktop && { flexDirection: 'column' }]}>
            {utilityIcons.map(renderUtilityIcon)}
          </View>
          {isDesktop && user ? (
            <View style={{ paddingHorizontal: space.xs }}>
              <T v="small" tone="muted" numberOfLines={1}>
                {maskEmail(user.email)}
              </T>
            </View>
          ) : null}
          {isDesktop ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Đăng xuất"
              onPress={() => signOut(false)}
              style={({ pressed }) => [
                styles.desktopItem,
                { backgroundColor: pressed ? c.surfaceAlt : 'transparent' },
              ]}>
              <Icon name="arrow-left" size={18} color={c.muted} />
              <T v="body" tone="muted">
                Đăng xuất
              </T>
            </Pressable>
          ) : null}
        </View>
      </View>

      <View style={{ flex: 1, minWidth: 0 }}>{children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  desktopRail: {
    width: 224,
    borderRightWidth: 1,
    paddingTop: space.lg,
    paddingBottom: space.md,
    justifyContent: 'space-between',
  },
  tabletRail: {
    width: 72,
    borderRightWidth: 1,
    paddingTop: space.lg,
    paddingBottom: space.md,
    justifyContent: 'space-between',
  },
  brandRowWrap: {
    marginBottom: space.sm,
  },
  brandRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingHorizontal: space.lg,
    paddingBottom: space.sm,
    borderBottomWidth: 1.5,
  },
  navList: {
    paddingHorizontal: space.sm,
    gap: 2,
    paddingVertical: space.xs,
  },
  desktopItem: {
    minHeight: 44,
    borderRadius: radius.sm,
    paddingHorizontal: space.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
  },
  tabletItem: {
    width: TOUCH,
    height: TOUCH,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  utilityRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.xs,
  },
  utilityIconBtn: {
    minWidth: 44,
    minHeight: 44,
    borderRadius: radius.sm,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  railFooter: {
    borderTopWidth: 1,
    paddingTop: space.md,
    paddingHorizontal: space.md,
    gap: space.sm,
  },
});
