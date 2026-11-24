import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';

import { api, call, refreshSession } from '@/api/client';
import { errorText } from '@/api/errors';
import { Button, ErrorBox, Field, LinkButton, Notice, Screen, T } from '@/components/ui';

/** Email verification landing target (`/xac-minh-email?token=...`). */
export default function VerifyEmail() {
  const params = useLocalSearchParams<{ token?: string }>();
  const router = useRouter();
  const [tokenInput, setTokenInput] = useState<{ base: string | undefined; value: string } | null>(null);
  const token = tokenInput && tokenInput.base === params.token ? tokenInput.value : (params.token ?? '');
  const setToken = (value: string) => setTokenInput({ base: params.token, value });
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const submit = async () => {
    if (!token.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await call(api.POST('/auth/verify-email/confirm', { body: { token: token.trim() } }));
      await refreshSession().catch(() => null);
      setDone(true);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen testID="screen-verify-email" variant="focused">
      <T v="h2" accessibilityRole="header">
        Xác minh email
      </T>
      <T tone="muted">Nhập mã xác minh từ hộp thư để hoàn tất xác thực địa chỉ email tài khoản.</T>
      <Field label="Mã xác minh" value={token} onChangeText={setToken} autoCapitalize="none" />
      {err ? <ErrorBox message={errorText(err)} /> : null}
      {done ? (
        <Notice tone="ok">
          <T>Email của bạn đã được xác minh thành công.</T>
        </Notice>
      ) : (
        <Button label="Xác minh email" onPress={submit} loading={busy} disabled={!token.trim()} />
      )}
      <LinkButton label="Về trang đăng nhập" onPress={() => router.replace('/dang-nhap')} />
    </Screen>
  );
}
