import { BeVietnamPro_400Regular } from '@expo-google-fonts/be-vietnam-pro/400Regular';
import { BeVietnamPro_500Medium } from '@expo-google-fonts/be-vietnam-pro/500Medium';
import { BeVietnamPro_600SemiBold } from '@expo-google-fonts/be-vietnam-pro/600SemiBold';
import { BeVietnamPro_700Bold } from '@expo-google-fonts/be-vietnam-pro/700Bold';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFonts } from 'expo-font';
import { Stack, useRouter, useSegments } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiError } from '@/api/client';
import { SessionProvider, useSession } from '@/auth/session';
import { startOutbox } from '@/lib/outbox';
import { font, ThemeProvider, useTheme } from '@/theme';

SplashScreen.preventAutoHideAsync().catch(() => {});

/** Routes reachable without an account. */
const PUBLIC = new Set(['dang-nhap', 'dang-ky', 'quen-mat-khau', 'dat-lai-mat-khau', 'khao-sat']);

export default function RootLayout() {
  const [loaded] = useFonts({ BeVietnamPro_400Regular, BeVietnamPro_500Medium, BeVietnamPro_600SemiBold, BeVietnamPro_700Bold });
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
    if (loaded) SplashScreen.hideAsync().catch(() => {});
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
  const { c, scheme } = useTheme();
  const { status } = useSession();
  const segments = useSegments();
  const router = useRouter();
  const first = segments.find((s) => !s.startsWith('(')) ?? '';

  useEffect(() => {
    if (status === 'loading') return;
    const isPublic = PUBLIC.has(first);
    if (status === 'signedOut' && !isPublic) router.replace('/dang-nhap');
    if (status === 'signedIn' && (first === 'dang-nhap' || first === 'dang-ky')) router.replace('/');
  }, [status, first, router]);

  useEffect(() => (status === 'signedIn' ? startOutbox() : undefined), [status]);

  return (
    <>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: c.bg },
          headerTintColor: c.accent,
          headerTitleStyle: { fontFamily: font.semibold, color: c.text },
          headerShadowVisible: false,
          contentStyle: { backgroundColor: c.bg },
          headerBackTitle: 'Quay lại',
        }}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="(auth)" options={{ headerShown: false }} />
        <Stack.Screen name="onboarding" options={{ headerShown: false }} />
        <Stack.Screen name="quet/index" options={{ title: 'Quét' }} />
        <Stack.Screen name="quet/[id]" options={{ title: 'Xác nhận nguyên liệu' }} />
        <Stack.Screen name="nau/[id]" options={{ title: 'Nấu cả mâm' }} />
        <Stack.Screen name="nau-xong/[id]" options={{ title: 'Nấu xong' }} />
        <Stack.Screen name="mon/[id]" options={{ title: 'Món' }} />
        <Stack.Screen name="cai-dat" options={{ title: 'Cài đặt' }} />
        <Stack.Screen name="khao-sat" options={{ title: 'Khảo sát gu món ăn' }} />
        <Stack.Screen name="dat-lai-mat-khau" options={{ title: 'Đặt lại mật khẩu' }} />
      </Stack>
    </>
  );
}
