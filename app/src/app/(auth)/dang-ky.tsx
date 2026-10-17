import { useRouter } from 'expo-router';
import { useState } from 'react';

import { errorText, fieldErrors } from '@/api/errors';
import { useSession } from '@/auth/session';
import { BrandHeader } from '@/components/Brand';
import { Button, ErrorBox, Field, LinkButton, Screen, T } from '@/components/ui';
import { isCode } from '@/api/client';

const MIN = 10;

export default function Register() {
  const { register } = useSession();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [again, setAgain] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const fe = fieldErrors(err);
  const mismatch = again.length > 0 && again !== password;

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      await register(email.trim(), password);
      router.replace('/onboarding');
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen testID="screen-register">
      <BrandHeader subtitle="Mâm cơm từ đồ đang có trong bếp" />
      <T v="h2" accessibilityRole="header">
        Tạo tài khoản
      </T>
      <Field
        label="Email"
        testID="register-email"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
        inputMode="email"
        error={fe.email ?? (isCode(err, 'invalid_email', 'email_taken') ? errorText(err) : undefined)}
      />
      <Field
        label="Mật khẩu"
        testID="register-password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoComplete="new-password"
        hint={`Ít nhất ${MIN} ký tự.`}
        error={fe.password ?? (isCode(err, 'weak_password') ? errorText(err) : undefined)}
      />
      <Field
        label="Nhập lại mật khẩu"
        testID="register-password2"
        value={again}
        onChangeText={setAgain}
        secureTextEntry
        autoComplete="new-password"
        error={mismatch ? 'Hai mật khẩu chưa khớp.' : undefined}
      />
      {err && !isCode(err, 'invalid_email', 'email_taken', 'weak_password') ? <ErrorBox message={errorText(err)} /> : null}
      {isCode(err, 'email_taken') ? (
        <LinkButton label="Đăng nhập bằng email này" onPress={() => router.replace('/dang-nhap')} />
      ) : null}
      <Button
        label="Tạo tài khoản"
        testID="register-submit"
        onPress={submit}
        loading={busy}
        disabled={!email || password.length < MIN || password !== again}
      />
      <LinkButton label="Đã có tài khoản? Đăng nhập" onPress={() => router.replace('/dang-nhap')} />
    </Screen>
  );
}
