import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';

import { api, call } from '@/api/client';
import { errorText } from '@/api/errors';
import { Button, ErrorBox, Field, LinkButton, Notice, Screen, T } from '@/components/ui';

/** Target of the reset mail link (`RESET_URL_BASE?token=`, UC04). */
export default function ResetPassword() {
  const params = useLocalSearchParams<{ token?: string }>();
  const router = useRouter();
  const [token, setToken] = useState(params.token ?? '');
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      await call(api.POST('/auth/password-reset/confirm', { body: { token: token.trim(), new_password: pw } }));
      setDone(true);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <T v="h2" accessibilityRole="header">
        Đặt mật khẩu mới
      </T>
      {!params.token ? <Field label="Mã trong thư" value={token} onChangeText={setToken} autoCapitalize="none" /> : null}
      <Field label="Mật khẩu mới" value={pw} onChangeText={setPw} secureTextEntry hint="Ít nhất 10 ký tự." autoComplete="new-password" />
      {err ? <ErrorBox message={errorText(err)} /> : null}
      {done ? (
        <Notice tone="ok">
          <T>Đã đổi mật khẩu. Mọi phiên đăng nhập cũ đã bị đóng; hãy đăng nhập lại.</T>
        </Notice>
      ) : (
        <Button label="Lưu mật khẩu mới" onPress={submit} loading={busy} disabled={!token || pw.length < 10} />
      )}
      <LinkButton label="Đăng nhập" onPress={() => router.replace('/dang-nhap')} />
    </Screen>
  );
}
