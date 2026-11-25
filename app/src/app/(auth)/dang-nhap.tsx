import { useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { isCode } from '@/api/client';
import { errorText, fieldErrors } from '@/api/errors';
import { useSession } from '@/auth/session';
import { AuthField, AuthLink, AuthShell } from '@/components/AuthShell';
import { Icon } from '@/components/domain';
import { Button, ErrorBox, Row, T } from '@/components/ui';
import { useTheme } from '@/theme';

export default function Login() {
  const { signIn } = useSession();
  const { c } = useTheme();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [totp, setTotp] = useState('');
  const [needMfa, setNeedMfa] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const fe = fieldErrors(err);

  const submit = async () => {
    if (busy || !email.trim() || !password) return;
    if (needMfa && totp.trim().length < 6) return;
    setBusy(true);
    setErr(null);
    try {
      await signIn(email.trim(), password, totp.trim() || undefined);
    } catch (e) {
      if (isCode(e, 'mfa_required', 'mfa_invalid')) setNeedMfa(true);
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell testID="screen-login" title="Đăng nhập Mỹ Vị" subtitle="Đăng nhập để quản lý tủ lạnh, gợi ý nấu ăn và theo dõi calo mỗi ngày.">
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
        returnKeyType={needMfa ? 'next' : 'go'}
        onSubmitEditing={needMfa ? undefined : submit}
        error={fe.password}
      />
      {needMfa ? (
        <AuthField
          label="Mã xác thực hai bước (6 chữ số)"
          placeholder="000000"
          testID="login-totp"
          value={totp}
          onChangeText={(v) => setTotp(v.replace(/[^0-9]/g, '').slice(0, 6))}
          keyboardType="number-pad"
          inputMode="numeric"
          maxLength={6}
          returnKeyType="go"
          onSubmitEditing={submit}
          error={isCode(err, 'mfa_invalid') ? errorText(err) : undefined}
        />
      ) : null}
      {err && !isCode(err, 'mfa_invalid') ? <ErrorBox message={errorText(err)} /> : null}
      <View style={{ alignItems: 'flex-end', marginTop: -12 }}>
        <AuthLink label="Quên mật khẩu?" onPress={() => router.push('/quen-mat-khau')} />
      </View>
      <Button
        label="Đăng nhập"
        accessibilityLabel="Đăng nhập"
        testID="login-submit"
        iconRight={<Icon name="arrow-right" size={18} color={!email.trim() || !password ? c.muted : c.onAccent} />}
        onPress={submit}
        loading={busy}
        disabled={!email.trim() || !password || (needMfa && totp.trim().length < 6)}
        style={{ minHeight: 56 }}
      />
      <Row style={{ justifyContent: 'center', gap: 4 }}>
        <T v="body" tone="muted">
          Bạn mới đến Mỹ Vị?
        </T>
        <AuthLink label="Tạo tài khoản" testID="go-register" onPress={() => router.push('/dang-ky')} />
      </Row>
    </AuthShell>
  );
}
