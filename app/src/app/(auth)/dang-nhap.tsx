import { useRouter } from 'expo-router';
import { useState } from 'react';

import { errorText, fieldErrors } from '@/api/errors';
import { useSession } from '@/auth/session';
import { AuthField, AuthLink, AuthShell } from '@/components/AuthShell';
import { View } from 'react-native';
import { Button, ErrorBox, Row, T } from '@/components/ui';

export default function Login() {
  const { signIn } = useSession();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const fe = fieldErrors(err);

  const submit = async () => {
    if (busy || !email.trim() || !password) return;
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
    <AuthShell testID="screen-login" title="Về bếp thôi." subtitle="Đăng nhập để tiếp tục câu chuyện bữa ngon của bạn.">
      <AuthField
        label="Email"
        placeholder="ban@example.com"
        autoCorrect={false}
        testID="login-email"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
        inputMode="email"
        error={fe.email}
      />
      <AuthField
        label="Mật khẩu"
        placeholder="Nhập mật khẩu của bạn"
        testID="login-password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        autoComplete="current-password"
        returnKeyType="go"
        onSubmitEditing={submit}
        error={fe.password}
      />
      {err ? <ErrorBox message={errorText(err)} /> : null}
      <View style={{ alignItems: 'flex-end', marginTop: -12 }}><AuthLink label="Quên mật khẩu?" onPress={() => router.push('/quen-mat-khau')} /></View>
      <Button label="Đăng nhập →" accessibilityLabel="Đăng nhập" testID="login-submit" onPress={submit} loading={busy} disabled={!email.trim() || !password} style={{ minHeight: 56, borderRadius: 12 }} />
      <Row style={{ justifyContent: 'center', gap: 4 }}>
        <T tone="muted" style={{ fontSize: 13 }}>Bạn mới đến Tastoria?</T>
        <AuthLink label="Tạo tài khoản" testID="go-register" onPress={() => router.push('/dang-ky')} />
      </Row>
    </AuthShell>
  );
}
