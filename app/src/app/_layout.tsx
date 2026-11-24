import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFonts } from 'expo-font';
import { DefaultTheme, Stack, ThemeProvider as NavThemeProvider, useRouter, useSegments } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiError } from '@/api/client';
import { SessionProvider, useSession } from '@/auth/session';
import { AppShell } from '@/components/AppShell';
import { PaperBackground } from '@/components/Brand';
import { startOutbox } from '@/lib/outbox';
import { font, ThemeProvider, useTheme } from '@/theme';

SplashScreen.preventAutoHideAsync().catch(() => { });

/** Routes reachable without an account. */
const PUBLIC = new Set(['dang-nhap', 'dang-ky', 'quen-mat-khau', 'dat-lai-mat-khau', 'xac-minh-email', 'khao-sat']);

export default function RootLayout() {
  const [loaded] = useFonts({
    BeVietnamPro_400Regular: require('../../assets/fonts/BeVietnamPro_400Regular.ttf'),
    BeVietnamPro_500Medium: require('../../assets/fonts/BeVietnamPro_500Medium.ttf'),
    BeVietnamPro_600SemiBold: require('../../assets/fonts/BeVietnamPro_600SemiBold.ttf'),
    BeVietnamPro_700Bold: require('../../assets/fonts/BeVietnamPro_700Bold.ttf'),
    Newsreader_500Medium: require('../../assets/fonts/Newsreader_500Medium.ttf'),
    Newsreader_600SemiBold: require('../../assets/fonts/Newsreader_600SemiBold.ttf'),
    Newsreader_700Bold: require('../../assets/fonts/Newsreader_700Bold.ttf'),
  });
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: (n, e) => n < 2 && (!(e instanceof ApiError) || e.status === 0 || e.status >= 500),
            staleTime: 15_000,
          },
        },
      }),
  );
  useEffect(() => {
    if (loaded) SplashScreen.hideAsync().catch(() => { });
  }, [loaded]);
  if (!loaded) return null;
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <QueryClientProvider client={qc}>
          <SessionProvider>
            <Shell />
          </SessionProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}

function Shell() {
  const { c } = useTheme();
  const { status, isNewAccount, consumeNewAccount } = useSession();
  const segments = useSegments();
  const router = useRouter();
  const first = segments.find((s) => !s.startsWith('(')) ?? '';

  useEffect(() => {
    if (status === 'loading') return;
    const isPublic = PUBLIC.has(first);
    if (status === 'signedOut' && !isPublic) router.replace('/dang-nhap');
    if (status === 'signedIn' && first === 'dang-nhap') router.replace('/bep');
    if (status === 'signedIn' && first === 'dang-ky') {
      if (isNewAccount) {
        consumeNewAccount?.();
        router.replace('/onboarding');
      } else {
        router.replace('/bep');
      }
    }
  }, [status, first, router, isNewAccount, consumeNewAccount]);

  useEffect(() => (status === 'signedIn' ? startOutbox() : undefined), [status]);

  const navTheme = {
    ...DefaultTheme,
    colors: {
      ...DefaultTheme.colors,
      background: 'transparent',
      card: c.surface,
      text: c.text,
      border: c.hairline,
      primary: c.accent,
      notification: c.accent,
    },
  };

  return (
    <PaperBackground testID="app-root">
      <StatusBar style="dark" />
      <NavThemeProvider value={navTheme}>
        <AppShell>
          <Stack
            screenOptions={{
              headerStyle: { backgroundColor: c.surface },
              headerTintColor: c.accent,
              headerTitleStyle: { fontFamily: font.semibold, color: c.text },
              headerShadowVisible: false,
              contentStyle: { backgroundColor: 'transparent' },
              headerBackTitle: 'Quay lại',
            }}>
            <Stack.Screen name="index" options={{ headerShown: false }} />
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="(auth)" options={{ headerShown: false }} />
            <Stack.Screen name="onboarding" options={{ headerShown: false }} />
            <Stack.Screen name="quet/index" options={{ title: '', headerBackTitle: 'Quay lại' }} />
            <Stack.Screen name="quet/[id]" options={{ title: '', headerBackTitle: 'Quay lại' }} />
            <Stack.Screen name="nau/[id]" options={{ title: '', headerBackTitle: 'Quay lại' }} />
            <Stack.Screen name="nau-xong/[id]" options={{ title: 'Nấu xong' }} />
            <Stack.Screen name="mon/[id]" options={{ title: 'Món' }} />
            <Stack.Screen name="kham-pha" options={{ title: '', headerBackTitle: 'Quay lại' }} />
            <Stack.Screen name="quan-tri" options={{ title: 'Quản trị hệ thống' }} />
            <Stack.Screen name="cai-dat" options={{ title: 'Cài đặt' }} />
            <Stack.Screen name="khao-sat" options={{ title: 'Khảo sát gu món ăn' }} />
            <Stack.Screen name="dat-lai-mat-khau" options={{ title: 'Đặt lại mật khẩu' }} />
            <Stack.Screen name="xac-minh-email" options={{ title: 'Xác minh email' }} />
          </Stack>
        </AppShell>
      </NavThemeProvider>
    </PaperBackground>
  );
}
