import { useRouter } from 'expo-router';
import { useState } from 'react';

import { errorText, fieldErrors } from '@/api/errors';
import { useSession } from '@/auth/session';
import { BrandHeader, PublicHomeLink } from '@/components/Brand';
import { Button, ErrorBox, Field, LinkButton, Row, Screen, T } from '@/components/ui';

export default function Login() {
  const { signIn } = useSession();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const fe = fieldErrors(err);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      await signIn(email.trim(), password);
      router.replace('/bep');
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen testID="screen-login">
      <BrandHeader />
      <T tone="muted">Đăng nhập để mở kho bếp, lên mâm và lưu lại những bữa ngon của bạn.</T>
      <T v="h2" accessibilityRole="header">
        Chào bạn, vào bếp thôi!
      </T>
      <Field
        label="Email"
        testID="login-email"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
        inputMode="email"
        error={fe.email}
      />
      <Field
        label="Mật khẩu"
        testID="login-password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoComplete="current-password"
        onSubmitEditing={submit}
        error={fe.password}
      />
      {err ? <ErrorBox message={errorText(err)} /> : null}
      <Button label="Đăng nhập" testID="login-submit" onPress={submit} loading={busy} disabled={!email || !password} />
      <Row style={{ justifyContent: 'space-between' }}>
        <LinkButton label="Quên mật khẩu?" onPress={() => router.push('/quen-mat-khau')} />
        <LinkButton label="Tạo tài khoản" testID="go-register" onPress={() => router.push('/dang-ky')} />
      </Row>
      <LinkButton label="Làm khảo sát gu món ăn (không cần tài khoản)" onPress={() => router.push('/khao-sat')} />
      <PublicHomeLink />
    </Screen>
  );
}
