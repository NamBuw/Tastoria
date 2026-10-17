import { useRouter } from 'expo-router';
import { useState } from 'react';

import { api, call } from '@/api/client';
import { errorText } from '@/api/errors';
import { BrandHeader } from '@/components/Brand';
import { Button, ErrorBox, Field, LinkButton, Notice, Screen, T } from '@/components/ui';

export default function ForgotPassword() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      await call(api.POST('/auth/password-reset/request', { body: { email: email.trim() } }));
      setSent(true);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen testID="screen-forgot">
      <BrandHeader />
      <T v="h2" accessibilityRole="header">
        Quên mật khẩu
      </T>
      <T tone="muted">Nhập email đã đăng ký. Nếu email có tài khoản, Tastoria gửi một liên kết đặt lại mật khẩu, dùng được trong 30 phút.</T>
      <Field
        label="Email"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
        inputMode="email"
        autoComplete="email"
      />
      {sent ? (
        <Notice tone="ok">
          <T>Đã gửi yêu cầu. Kiểm tra hộp thư (cả mục thư rác). Chưa thấy thư sau 1 phút thì gửi lại.</T>
        </Notice>
      ) : null}
      {err ? <ErrorBox message={errorText(err)} /> : null}
      <Button label={sent ? 'Gửi lại' : 'Gửi liên kết'} onPress={submit} loading={busy} disabled={!email} />
      <LinkButton label="Đã có liên kết? Nhập mã đặt lại" onPress={() => router.push('/dat-lai-mat-khau')} />
      <LinkButton label="Quay lại đăng nhập" onPress={() => router.replace('/dang-nhap')} />
    </Screen>
  );
}
