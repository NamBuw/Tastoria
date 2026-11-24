import { useMutation, useQueries, useQuery, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { type Href, useRouter } from 'expo-router';
import { useState, type ReactNode } from 'react';
import { Platform, Pressable, View } from 'react-native';

import { api, API_URL, ApiError, call, refreshSession, setSession, type Schemas } from '@/api/client';
import { errorText, fieldErrors } from '@/api/errors';
import { useSession } from '@/auth/session';
import { maskEmail } from '@/components/AppShell';
import { Icon } from '@/components/domain';
import { PolicyCard } from '@/components/PolicyCard';
import {
  ActivityGoalFields,
  AllergenDietFields,
  BodyFields,
  draftToUpdate,
  EnergyTargetPanel,
  FavoritesPicker,
  profileToDraft,
  validateBodyDraft,
  type BodyDraft,
} from '@/components/profileForms';
import { Button, Card, ErrorBox, Field, Loading, Notice, Row, Screen, Segmented, Stepper, T } from '@/components/ui';
import { qk, useConsents, useProfile, useSettings } from '@/lib/queries';
import { radius, space, TOUCH, useTheme } from '@/theme';

/** Cài đặt (UC03, UC05–UC08, UC10, UC11). */
export default function Settings() {
  const { user, signOut } = useSession();
  const { c } = useTheme();
  const router = useRouter();
  const [open, setOpen] = useState<string | null>(null);
  const isStaff = user?.role === 'admin' || user?.role === 'ml_operator';

  return (
    <Screen testID="screen-settings" variant="focused">
      <View style={{ gap: 4 }}>
        <T v="h1" accessibilityRole="header">
          Cài đặt tài khoản
        </T>
        <T tone="muted">Đăng nhập bằng {user?.email ? maskEmail(user.email) : ''}</T>
      </View>

      {isStaff ? (
        <Card style={{ borderColor: c.info, backgroundColor: c.infoSoft, gap: space.sm }}>
          <Row gap={space.sm}>
            <Icon name="shield" size={20} color={c.info} />
            <T v="h2" accessibilityRole="header" tone="info">
              Bảng quản trị &amp; vận hành mô hình
            </T>
          </Row>
          <T>Xem hàng đợi yêu cầu dữ liệu, nhật ký kiểm toán, phiên bản mô hình và tiến độ khảo sát.</T>
          <Button
            label="Mở bảng Quản trị"
            kind="secondary"
            testID="settings-open-admin"
            onPress={() => router.push('/quan-tri' as Href)}
          />
        </Card>
      ) : null}

      <Card style={{ padding: 0, gap: 0, overflow: 'hidden' }}>
        {GROUPS.filter(([k]) => k !== 'delete').map(([k, title, Body], idx) => (
          <Group
            key={k}
            k={k}
            title={title}
            divided={idx > 0}
            open={open === k}
            toggle={() => setOpen(open === k ? null : k)}>
            <Body />
          </Group>
        ))}
      </Card>

      {GROUPS.filter(([k]) => k === 'delete').map(([k, title, Body]) => (
        <Card key={k} style={{ padding: 0, gap: 0, overflow: 'hidden', borderColor: c.danger, borderWidth: 1 }}>
          <Group
            k={k}
            title={title}
            danger
            open={open === k}
            toggle={() => setOpen(open === k ? null : k)}>
            <Body />
          </Group>
        </Card>
      ))}
      <Button label="Làm khảo sát gu món ăn" kind="secondary" onPress={() => router.push('/khao-sat')} />
      <Button label="Đăng xuất" kind="secondary" testID="sign-out" onPress={() => signOut(false)} />
      <Button label="Đăng xuất mọi thiết bị" kind="ghost" onPress={() => signOut(true)} />
    </Screen>
  );
}

function Group({
  k,
  title,
  danger,
  divided,
  open: isOpen,
  toggle,
  children,
}: {
  k: string;
  title: string;
  danger?: boolean;
  divided?: boolean;
  open: boolean;
  toggle: () => void;
  children: ReactNode;
}) {
  const { c } = useTheme();
  return (
    <View style={divided ? { borderTopWidth: 1, borderTopColor: c.hairline } : undefined}>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: isOpen }}
        testID={`settings-${k}`}
        onPress={toggle}
        style={({ pressed }) => ({
          minHeight: TOUCH + 8,
          paddingHorizontal: space.lg,
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: space.sm,
          backgroundColor: pressed ? c.surfaceAlt : 'transparent',
        })}>
        <T v="title" tone={danger ? 'danger' : 'text'} style={{ flexShrink: 1 }}>
          {title}
        </T>
        <Icon name={isOpen ? 'minus' : 'plus'} size={20} color={danger ? c.danger : c.accent} />
      </Pressable>
      {isOpen ? <View style={{ paddingHorizontal: space.lg, paddingBottom: space.lg, gap: space.md }}>{children}</View> : null}
    </View>
  );
}

function ProfileSection() {
  const qc = useQueryClient();
  const profile = useProfile();
  const [draftState, setDraftState] = useState<{ base: number; draft: BodyDraft } | null>(null);
  const [saved, setSaved] = useState(false);
  const [target, setTarget] = useState(false);

  const p = profile.data;
  const baseDraft = p ? profileToDraft(p) : null;
  const draft =
    draftState && draftState.base === profile.dataUpdatedAt ? draftState.draft : baseDraft;

  const save = useMutation({
    mutationFn: (adult: boolean) => call(api.PUT('/me/profile', { body: draftToUpdate(draft!, adult) })),
    onSuccess: () => {
      setSaved(true);
      qc.invalidateQueries({ queryKey: qk.profile });
    },
  });

  if (profile.isLoading) return <Loading />;
  if (profile.error) return <ErrorBox message={errorText(profile.error)} onRetry={() => profile.refetch()} />;
  if (!p) return null;
  if (!p.health_profile_consented) {
    return (
      <Notice>
        <T>Bạn chưa đồng ý lưu hồ sơ sức khoẻ nên Mỹ Vị chưa tính mục tiêu năng lượng. Bật trong mục &quot;Đồng ý sử dụng dữ liệu&quot;.</T>
      </Notice>
    );
  }
  if (!draft) return <Loading />;

  const set = (x: Partial<BodyDraft>) => {
    setSaved(false);
    setDraftState((cur) => {
      const current = cur && cur.base === profile.dataUpdatedAt ? cur.draft : profileToDraft(p);
      return { base: profile.dataUpdatedAt, draft: { ...current, ...x } };
    });
  };
  const draftErrors = validateBodyDraft(draft);
  const hasDraftErrors = Object.keys(draftErrors).length > 0;

  return (
    <View style={{ gap: space.md }}>
      <T>
        Mục tiêu hiện tại:{' '}
        {p.kcal_target ? `${p.kcal_target.toLocaleString('vi-VN')} kcal/ngày (${p.kcal_source === 'suggested' ? 'gợi ý' : p.kcal_source === 'expert' ? 'chuyên gia đặt' : 'tự nhập'})` : 'chưa có'}
      </T>
      {p.target_stale ? (
        <Notice tone="warn">
          <T>Hồ sơ đã đổi sau lần đặt mục tiêu{p.suggested_kcal ? `; gợi ý mới là ${p.suggested_kcal} kcal/ngày` : ''}.</T>
        </Notice>
      ) : null}
      <BodyFields d={draft} set={set} errors={{ ...draftErrors, ...fieldErrors(save.error) }} />
      <ActivityGoalFields d={draft} set={set} />
      {save.error instanceof ApiError && save.error.code === 'age_confirmation_required' ? (
        <Notice>
          <T>Theo năm sinh, bạn có thể mới 17 tuổi. Bạn đã đủ 18 tuổi chưa?</T>
          <Button label="Tôi đã đủ 18 tuổi" onPress={() => save.mutate(true)} />
        </Notice>
      ) : save.error ? (
        <ErrorBox message={errorText(save.error)} />
      ) : null}
      {saved ? <T tone="muted">Đã lưu hồ sơ.</T> : null}
      <Button label="Lưu hồ sơ" onPress={() => save.mutate(false)} loading={save.isPending} disabled={hasDraftErrors} />
      {draft.goal ? (
        target ? (
          <EnergyTargetPanel
            goal={draft.goal}
            onSaved={() => {
              setTarget(false);
              qc.invalidateQueries({ queryKey: qk.profile });
            }}
            onLater={() => setTarget(false)}
          />
        ) : (
          <Button label="Đặt lại mục tiêu năng lượng" kind="secondary" onPress={() => setTarget(true)} />
        )
      ) : null}
    </View>
  );
}

type AllergenDraft = { a: string[]; none: boolean; diet: string | null };

function AllergenSection() {
  const qc = useQueryClient();
  const profile = useProfile();
  const [state, setState] = useState<{ base: number; val: AllergenDraft } | null>(null);

  const p = profile.data;
  const cur: AllergenDraft | null =
    state && state.base === profile.dataUpdatedAt
      ? state.val
      : p
        ? { a: p.allergen_codes, none: p.allergen_codes.length === 0, diet: p.diet_code }
        : null;

  const update = (patch: Partial<AllergenDraft>) => {
    if (!p) return;
    setState((prev) => {
      const baseVal =
        prev && prev.base === profile.dataUpdatedAt
          ? prev.val
          : { a: p.allergen_codes, none: p.allergen_codes.length === 0, diet: p.diet_code };
      return { base: profile.dataUpdatedAt, val: { ...baseVal, ...patch } };
    });
  };

  const save = useMutation({
    mutationFn: async () => {
      await call(api.PUT('/me/allergens', { body: { allergen_codes: cur?.none ? [] : cur?.a ?? [] } }));
      await call(api.PUT('/me/diet', { body: { diet_code: cur?.diet ?? null } }));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.profile }),
  });

  if (profile.isLoading) return <Loading />;
  if (profile.error) return <ErrorBox message={errorText(profile.error)} onRetry={() => profile.refetch()} />;
  if (!cur) return <Loading />;

  return (
    <View style={{ gap: space.md }}>
      <AllergenDietFields
        allergens={cur.a}
        none={cur.none}
        diet={cur.diet}
        onAllergens={(a) => update({ a })}
        onNone={(none) => update({ none })}
        onDiet={(diet) => update({ diet })}
      />
      <SaveButton m={save} disabled={!cur.none && !cur.a.length} />
    </View>
  );
}

function FavsSection() {
  const qc = useQueryClient();
  const profile = useProfile();
  const [state, setState] = useState<{ base: number; ids: string[] } | null>(null);

  const p = profile.data;
  const ids =
    state && state.base === profile.dataUpdatedAt
      ? state.ids
      : (p?.favorite_recipe_ids ?? null);

  const save = useMutation({
    mutationFn: () => call(api.PUT('/me/favorites', { body: { recipe_ids: ids ?? [] } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.profile }),
  });

  if (profile.isLoading) return <Loading />;
  if (profile.error) return <ErrorBox message={errorText(profile.error)} onRetry={() => profile.refetch()} />;
  if (ids === null) return <Loading />;

  return (
    <View style={{ gap: space.md }}>
      <FavoritesPicker selected={ids} onChange={(next) => setState({ base: profile.dataUpdatedAt, ids: next })} />
      <SaveButton m={save} />
    </View>
  );
}

function KitchenSection() {
  const qc = useQueryClient();
  const settings = useSettings();
  const [state, setState] = useState<{ base: number; s: Schemas['UserSettings'] } | null>(null);

  const s =
    state && state.base === settings.dataUpdatedAt
      ? state.s
      : (settings.data ?? null);

  const save = useMutation({
    mutationFn: () =>
      call(api.PUT('/me/settings', { body: { burners: s!.burners, default_persons: s!.default_persons, timezone: s!.timezone } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.settings }),
  });

  if (settings.isLoading) return <Loading />;
  if (settings.error) return <ErrorBox message={errorText(settings.error)} onRetry={() => settings.refetch()} />;
  if (!s) return <Loading />;

  return (
    <View style={{ gap: space.md }}>
      <Stepper
        label="Số họng bếp"
        value={s.burners}
        min={1}
        max={4}
        onChange={(v) => setState({ base: settings.dataUpdatedAt, s: { ...s, burners: v } })}
      />
      <Stepper
        label="Số người ăn mặc định"
        value={s.default_persons}
        min={1}
        max={6}
        onChange={(v) => setState({ base: settings.dataUpdatedAt, s: { ...s, default_persons: v } })}
      />
      <T v="small" tone="muted">
        Múi giờ: {s.timezone}
      </T>
      <SaveButton m={save} />
    </View>
  );
}

/** Error, "Đã lưu." and the Lưu button under an editable settings section. */
function SaveButton({ m, disabled }: { m: UseMutationResult<unknown, Error, void>; disabled?: boolean }) {
  return (
    <>
      {m.error ? <ErrorBox message={errorText(m.error)} /> : null}
      {m.isSuccess ? <T tone="muted">Đã lưu.</T> : null}
      <Button label="Lưu" onPress={() => m.mutate()} loading={m.isPending} disabled={disabled} />
    </>
  );
}

const PURPOSES = ['health_profile', 'personalization', 'photo_contribution'] as const;

function ConsentSection() {
  const qc = useQueryClient();
  const consents = useConsents();
  const policies = useQueries({
    queries: PURPOSES.map((p) => ({
      queryKey: ['policy', p],
      queryFn: () => call(api.GET('/policies/{purpose}/current', { params: { path: { purpose: p } } })),
    })),
  });
  const change = useMutation({
    mutationFn: async ({ policy, grant }: { policy: Schemas['PolicyVersion']; grant: boolean }) => {
      if (grant)
        await call(
          api.POST('/me/consents', { body: { channel: 'settings', decisions: [{ policy_version_id: policy.id, action: 'grant' }] } }),
        );
      else
        await call(
          api.POST('/me/consents/{purpose}/withdraw', {
            params: { path: { purpose: policy.purpose_code } },
            body: { channel: 'settings' },
          }),
        );
      // withdrawing raises token_version: get a fresh access token before the next call
      if (!grant) await refreshSession();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.consents });
      qc.invalidateQueries({ queryKey: qk.profile });
    },
  });

  if (consents.isLoading || policies.some((p) => p.isLoading)) return <Loading />;
  const policyErr = policies.find((p) => p.error)?.error;
  if (consents.error || policyErr) {
    return (
      <ErrorBox
        message={errorText(consents.error ?? policyErr)}
        onRetry={() => {
          consents.refetch();
          policies.forEach((p) => p.refetch());
        }}
      />
    );
  }

  return (
    <View style={{ gap: space.md }}>
      <T tone="muted">
        Rút đồng ý &quot;Cá nhân hoá&quot; xoá lịch sử tương tác dùng để học gu; rút &quot;Hồ sơ sức khoẻ&quot; xoá chỉ số cơ thể. Việc xoá hoàn tất trong 24
        giờ.
      </T>
      {policies.map((pq) => {
        const p = pq.data;
        if (!p) return null;
        const st = consents.data?.items.find((i) => i.purpose_code === p.purpose_code);
        const granted = st?.state === 'granted';
        const outdated = granted && st?.policy_version_id !== st?.current_policy_version_id;
        return (
          <View key={p.id} style={{ gap: space.xs }}>
            <PolicyCard
              policy={p}
              checked={granted && !outdated}
              disabled={change.isPending}
              onChange={(v) => change.mutate({ policy: p, grant: v })}
            />
            {outdated ? <T v="small" tone="danger">Điều khoản đã có bản mới; tích lại để đồng ý bản mới.</T> : null}
          </View>
        );
      })}
      {change.error ? <ErrorBox message={errorText(change.error)} /> : null}
    </View>
  );
}

function VerifyEmailSection() {
  const { user } = useSession();
  const [token, setToken] = useState('');
  const [confirmed, setConfirmed] = useState(false);

  const requestMail = useMutation({
    mutationFn: () => call(api.POST('/auth/verify-email/request')),
  });

  const confirmMail = useMutation({
    mutationFn: async () => {
      await call(api.POST('/auth/verify-email/confirm', { body: { token: token.trim() } }));
      await refreshSession().catch(() => null);
    },
    onSuccess: () => {
      setConfirmed(true);
      setToken('');
    },
  });

  const verified = Boolean(user?.email_verified || confirmed);

  return (
    <View style={{ gap: space.md }} testID="settings-verify-email-section">
      <Notice tone={verified ? 'ok' : 'warn'}>
        <T v="label">
          {verified ? 'Địa chỉ email đã được xác minh.' : 'Địa chỉ email chưa được xác minh.'}
        </T>
        {!verified ? (
          <T v="small" tone="muted">
            Xác minh email giúp bảo vệ tài khoản và nhận thông báo đặt lại mật khẩu an toàn.
          </T>
        ) : null}
      </Notice>

      {!verified ? (
        <>
          {requestMail.error ? <ErrorBox message={errorText(requestMail.error)} /> : null}
          {requestMail.isSuccess ? (
            <Notice tone="ok">
              <T>Đã gửi thư xác minh email. Vui lòng kiểm tra hộp thư (kể cả mục thư rác).</T>
            </Notice>
          ) : null}
          <Button
            label={requestMail.isSuccess ? 'Gửi lại thư xác minh' : 'Gửi thư xác minh email'}
            kind="secondary"
            testID="verify-email-resend"
            loading={requestMail.isPending}
            onPress={() => requestMail.mutate()}
          />
          <Field
            label="Hoặc nhập mã xác minh từ hộp thư"
            testID="verify-email-token"
            value={token}
            onChangeText={setToken}
            autoCapitalize="none"
            placeholder="Dán mã xác minh…"
          />
          {confirmMail.error ? <ErrorBox message={errorText(confirmMail.error)} /> : null}
          <Button
            label="Xác nhận mã"
            testID="verify-email-confirm-btn"
            disabled={!token.trim()}
            loading={confirmMail.isPending}
            onPress={() => confirmMail.mutate()}
          />
        </>
      ) : null}
    </View>
  );
}

function ChangePasswordSection() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [done, setDone] = useState(false);

  const mismatch = confirmPassword.length > 0 && confirmPassword !== newPassword;

  const submit = useMutation({
    mutationFn: async () => {
      const nextSession = await call(
        api.POST('/auth/change-password', {
          body: { current_password: currentPassword, new_password: newPassword },
        }),
      );
      await setSession(nextSession);
    },
    onSuccess: () => {
      setDone(true);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    },
  });

  const canSubmit = currentPassword.length > 0 && newPassword.length >= 10 && newPassword === confirmPassword;

  return (
    <View style={{ gap: space.md }} testID="settings-change-password-section">
      <T v="small" tone="muted">
        Đổi mật khẩu sẽ đóng tất cả các phiên đăng nhập trên thiết bị khác và giữ nguyên phiên hiện tại.
      </T>
      <Field
        label="Mật khẩu hiện tại"
        testID="cp-current"
        value={currentPassword}
        onChangeText={(v) => {
          setDone(false);
          setCurrentPassword(v);
        }}
        secureTextEntry
        autoComplete="current-password"
      />
      <Field
        label="Mật khẩu mới"
        testID="cp-new"
        value={newPassword}
        onChangeText={(v) => {
          setDone(false);
          setNewPassword(v);
        }}
        secureTextEntry
        autoComplete="new-password"
        hint="Ít nhất 10 ký tự."
      />
      <Field
        label="Nhập lại mật khẩu mới"
        testID="cp-confirm"
        value={confirmPassword}
        onChangeText={(v) => {
          setDone(false);
          setConfirmPassword(v);
        }}
        secureTextEntry
        autoComplete="new-password"
        error={mismatch ? 'Hai mật khẩu mới chưa khớp.' : undefined}
      />
      {submit.error ? <ErrorBox message={errorText(submit.error)} /> : null}
      {done ? (
        <Notice tone="ok">
          <T>Đã đổi mật khẩu thành công.</T>
        </Notice>
      ) : null}
      <Button
        label="Cập nhật mật khẩu"
        testID="cp-submit"
        disabled={!canSubmit}
        loading={submit.isPending}
        onPress={() => submit.mutate()}
      />
    </View>
  );
}

function fmtSessionTime(iso?: string | null): string {
  if (!iso) return 'chưa rõ';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('vi-VN');
}

function SessionsSection() {
  const { c } = useTheme();
  const { signOut } = useSession();
  const qc = useQueryClient();
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const q = useQuery({
    queryKey: qk.authSessions,
    queryFn: () => call(api.GET('/auth/sessions')),
  });

  const revoke = useMutation({
    mutationFn: async (session: Schemas['SessionOut']) => {
      setRevokingId(session.id);
      await call(api.DELETE('/auth/sessions/{session_id}', { params: { path: { session_id: session.id } } }));
      return session;
    },
    onSuccess: (session) => {
      if (session.is_current) {
        void signOut(false);
        return;
      }
      qc.invalidateQueries({ queryKey: qk.authSessions });
    },
    onSettled: () => setRevokingId(null),
  });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} />;
  const items = q.data?.items ?? [];

  return (
    <View style={{ gap: space.md }} testID="settings-sessions-section">
      <T v="small" tone="muted">
        Danh sách thiết bị và trình duyệt đang giữ phiên đăng nhập của tài khoản này.
      </T>
      {items.length === 0 ? <T tone="muted">Không có phiên đăng nhập nào đang hoạt động.</T> : null}
      {items.map((sess) => (
        <View
          key={sess.id}
          testID={`session-row-${sess.id}`}
          style={{
            borderWidth: 1,
            borderColor: sess.is_current ? c.herb : c.hairline,
            backgroundColor: sess.is_current ? c.herbSoft : c.surfaceAlt,
            borderRadius: radius.sm,
            padding: space.md,
            gap: space.xs,
          }}>
          <Row style={{ justifyContent: 'space-between', flexWrap: 'wrap' }} gap={space.xs}>
            <T v="label" style={{ flex: 1, minWidth: 0 }} numberOfLines={2}>
              {sess.user_agent || 'Thiết bị không rõ trình duyệt'}
            </T>
            {sess.is_current ? (
              <View style={{ backgroundColor: c.surface, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 2 }}>
                <T v="small" tone="herb" style={{ fontWeight: '600' }}>
                  Phiên hiện tại
                </T>
              </View>
            ) : null}
          </Row>
          <T v="small" tone="muted" tabular>
            {sess.ip_address ? `IP: ${sess.ip_address}, ` : ''}
            Dùng gần nhất: {fmtSessionTime(sess.last_used_at ?? sess.issued_at)}
          </T>
          <Row style={{ justifyContent: 'flex-end' }}>
            <Button
              label="Thu hồi phiên"
              kind="secondary"
              compact
              testID={`session-revoke-${sess.id}`}
              loading={revokingId === sess.id && revoke.isPending}
              onPress={() => revoke.mutate(sess)}
            />
          </Row>
        </View>
      ))}
      {revoke.error ? <ErrorBox message={errorText(revoke.error)} /> : null}
    </View>
  );
}

function MfaSection() {
  const { user, signOut } = useSession();
  const { c } = useTheme();
  const [setupData, setSetupData] = useState<Schemas['MfaSetupOut'] | null>(null);
  const [code, setCode] = useState('');
  const [disablePw, setDisablePw] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [enabledNow, setEnabledNow] = useState(false);

  const isEnabled = Boolean(user?.mfa_enabled || enabledNow);

  const startSetup = useMutation({
    mutationFn: () => call(api.POST('/auth/mfa/setup')),
    onSuccess: (res) => {
      setSetupData(res);
      setCode('');
    },
  });

  const verifySetup = useMutation({
    mutationFn: async () => {
      const sess = await call(api.POST('/auth/mfa/verify', { body: { code: code.trim() } }));
      await setSession(sess);
    },
    onSuccess: () => {
      setSetupData(null);
      setCode('');
      setEnabledNow(true);
    },
  });

  const disableMfa = useMutation({
    mutationFn: () =>
      call(api.POST('/auth/mfa/disable', { body: { password: disablePw, code: disableCode.trim() } })),
    onSuccess: () => {
      setEnabledNow(false);
      void signOut(false);
    },
  });

  return (
    <View style={{ gap: space.md }} testID="settings-mfa-section">
      <Notice tone={isEnabled ? 'ok' : 'info'}>
        <T v="label">{isEnabled ? 'Xác thực hai bước (TOTP) đang bật.' : 'Xác thực hai bước (TOTP) đang tắt.'}</T>
      </Notice>

      {!isEnabled ? (
        setupData ? (
          <View style={{ gap: space.md }}>
            <T v="small" tone="muted">
              Nhập khoá bí mật sau vào ứng dụng xác thực (Google Authenticator, 1Password, …), sau đó nhập mã 6 chữ số để kích hoạt:
            </T>
            <View style={{ backgroundColor: c.surfaceAlt, borderRadius: radius.sm, padding: space.md, borderWidth: 1, borderColor: c.hairline }}>
              <T v="label" tabular selectable>
                {setupData.secret}
              </T>
            </View>
            <Field
              label="Mã TOTP 6 chữ số"
              value={code}
              onChangeText={(v) => setCode(v.replace(/[^0-9]/g, '').slice(0, 6))}
              keyboardType="number-pad"
              inputMode="numeric"
              maxLength={6}
              placeholder="000000"
            />
            {verifySetup.error ? <ErrorBox message={errorText(verifySetup.error)} /> : null}
            <Row gap={space.sm}>
              <Button
                label="Kích hoạt xác thực hai bước"
                disabled={code.trim().length < 6}
                loading={verifySetup.isPending}
                onPress={() => verifySetup.mutate()}
              />
              <Button label="Huỷ" kind="ghost" onPress={() => setSetupData(null)} />
            </Row>
          </View>
        ) : (
          <>
            {startSetup.error ? <ErrorBox message={errorText(startSetup.error)} /> : null}
            <Button
              label="Bật xác thực hai bước"
              kind="secondary"
              loading={startSetup.isPending}
              onPress={() => startSetup.mutate()}
            />
          </>
        )
      ) : (
        <View style={{ gap: space.md }}>
          <Field
            label="Mật khẩu hiện tại"
            value={disablePw}
            onChangeText={setDisablePw}
            secureTextEntry
            autoComplete="current-password"
          />
          <Field
            label="Mã TOTP hiện tại (6 chữ số)"
            value={disableCode}
            onChangeText={(v) => setDisableCode(v.replace(/[^0-9]/g, '').slice(0, 6))}
            keyboardType="number-pad"
            inputMode="numeric"
            maxLength={6}
            placeholder="000000"
          />
          {disableMfa.error ? <ErrorBox message={errorText(disableMfa.error)} /> : null}
          <Button
            label="Tắt xác thực hai bước"
            kind="danger"
            disabled={!disablePw || disableCode.trim().length < 6}
            loading={disableMfa.isPending}
            onPress={() => disableMfa.mutate()}
          />
        </View>
      )}
    </View>
  );
}

function ExportSection() {
  const [reqId, setReqId] = useState<string | null>(null);
  const [dlErr, setDlErr] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => call(api.POST('/me/data-requests', { body: { type: 'export' } })),
    onSuccess: (r) => setReqId(r.id),
  });
  const status = useQuery({
    queryKey: ['dsr', reqId],
    queryFn: () => call(api.GET('/me/data-requests/{id}', { params: { path: { id: reqId! } } })),
    enabled: !!reqId,
    refetchInterval: (q) => {
      if (q.state.error) return false;
      const st = q.state.data?.status;
      if (st === 'completed' || st === 'rejected') return false;
      return 3000;
    },
  });

  const download = async () => {
    setDlErr(null);
    try {
      const r = await api.GET('/me/data-requests/{id}/download', { params: { path: { id: reqId! } }, parseAs: 'blob' });
      if (!r.response.ok || !r.data) {
        setDlErr(errorText(new ApiError(r.response.status, (r.error as never) ?? null)));
        return;
      }
      if (Platform.OS === 'web') {
        const url = URL.createObjectURL(r.data as Blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'my-vi-du-lieu.zip';
        a.style.display = 'none';
        document.body.appendChild(a);
        try {
          a.click();
        } finally {
          a.remove();
          const timer = setTimeout(() => {
            URL.revokeObjectURL(url);
          }, 10_000);
          if (typeof (timer as unknown as { unref?: () => void }).unref === 'function') {
            (timer as unknown as { unref: () => void }).unref();
          }
        }
      } else {
        setDlErr(`Tệp đã sẵn sàng. Bản Android chưa lưu tệp được; tải trên bản web tại ${API_URL || 'trang Mỹ Vị'}.`);
      }
    } catch (e) {
      setDlErr(errorText(e));
    }
  };

  const d = status.data;
  const canRequestAgain = !reqId || d?.status === 'rejected';

  return (
    <View style={{ gap: space.md }}>
      <T tone="muted">Tệp ZIP chứa dữ liệu cá nhân Mỹ Vị đang lưu về bạn. Chậm nhất 24 giờ sau khi gửi yêu cầu.</T>
      {d ? (
        <T>
          Trạng thái: {DSR_STATUS_VI[d.status] ?? d.status}
          {d.status !== 'completed' && d.status !== 'rejected' ? `, hạn ${new Date(d.due_at).toLocaleString('vi-VN')}` : ''}
        </T>
      ) : null}
      {status.error ? <ErrorBox message={errorText(status.error)} onRetry={() => status.refetch()} /> : null}
      {create.error ? <ErrorBox message={errorText(create.error)} /> : null}
      {dlErr ? <Notice tone="warn"><T>{dlErr}</T></Notice> : null}
      {d?.download_available ? (
        <Button label="Tải tệp (.zip)" onPress={download} />
      ) : (
        <Button
          label="Gửi yêu cầu tải dữ liệu"
          onPress={() => create.mutate()}
          loading={create.isPending}
          disabled={!canRequestAgain}
        />
      )}
    </View>
  );
}

type ManualDsrType = 'correct' | 'restrict' | 'object';

const MANUAL_DSR_TYPE_LABEL: Record<string, string> = {
  correct: 'Chỉnh sửa dữ liệu sai lệch',
  restrict: 'Hạn chế xử lý dữ liệu',
  object: 'Phản đối xử lý dữ liệu',
};

const DSR_STATUS_VI: Record<string, string> = {
  received: 'đã tiếp nhận',
  in_progress: 'đang xử lý',
  completed: 'hoàn tất',
  rejected: 'từ chối',
};

function ManualDsrSection() {
  const [dsrType, setDsrType] = useState<ManualDsrType>('correct');
  const [note, setNote] = useState('');
  const [created, setCreated] = useState<Schemas['DataRequest'] | null>(null);
  const submit = useMutation({
    mutationFn: () =>
      call(
        api.POST('/me/data-requests', {
          body: { type: dsrType, note: note.trim() },
        }),
      ),
    onSuccess: (res) => {
      setCreated(res);
      setNote('');
    },
  });
  return (
    <View style={{ gap: space.md }}>
      <T tone="muted">
        Gửi yêu cầu chỉnh sửa thông tin sai lệch, hạn chế xử lý hoặc phản đối sử dụng dữ liệu tới quản trị viên.
      </T>
      <Segmented<ManualDsrType>
        label="Loại yêu cầu"
        column={space.sm}
        options={[
          ['correct', 'Chỉnh sửa dữ liệu sai lệch'],
          ['restrict', 'Hạn chế xử lý dữ liệu'],
          ['object', 'Phản đối xử lý dữ liệu'],
        ]}
        value={dsrType}
        onChange={setDsrType}
      />
      <Field
        label="Nội dung yêu cầu"
        testID="dsr-manual-note"
        value={note}
        onChangeText={setNote}
        multiline
        maxLength={2000}
        placeholder="Mô tả dữ liệu cần chỉnh sửa hoặc yêu cầu cụ thể…"
        hint="Bắt buộc, tối đa 2.000 ký tự."
      />
      {submit.error ? <ErrorBox message={errorText(submit.error)} /> : null}
      {created ? (
        <Notice tone="ok">
          <T>
            Đã gửi yêu cầu {MANUAL_DSR_TYPE_LABEL[created.type] ?? created.type}, trạng thái{' '}
            {DSR_STATUS_VI[created.status] ?? created.status}, hạn xử lý{' '}
            {new Date(created.due_at).toLocaleString('vi-VN')}
          </T>
        </Notice>
      ) : null}
      <Button
        label="Gửi yêu cầu"
        testID="dsr-manual-submit"
        onPress={() => submit.mutate()}
        loading={submit.isPending}
        disabled={note.trim().length === 0}
      />
    </View>
  );
}

function DeleteSection() {
  const { signOut } = useSession();
  const [pw, setPw] = useState('');
  const [sure, setSure] = useState(false);
  const del = useMutation({
    mutationFn: () => call(api.POST('/me/data-requests', { body: { type: 'delete', password: pw } })),
    onSuccess: () => signOut(false),
  });
  return (
    <View style={{ gap: space.md }}>
      <T>Xoá tài khoản xoá hồ sơ, kho, mâm, nhật ký và ảnh của bạn trong 24 giờ. Không khôi phục được.</T>
      <Field label="Nhập mật khẩu để xác nhận" value={pw} onChangeText={setPw} secureTextEntry autoComplete="current-password" />
      {del.error ? <ErrorBox message={errorText(del.error)} /> : null}
      {sure ? (
        <Row>
          <Button label="Xoá vĩnh viễn" kind="danger" onPress={() => del.mutate()} loading={del.isPending} disabled={!pw} />
          <Button label="Thôi" kind="ghost" onPress={() => setSure(false)} />
        </Row>
      ) : (
        <Button label="Xoá tài khoản" kind="danger" onPress={() => setSure(true)} disabled={!pw} />
      )}
    </View>
  );
}

const GROUPS: [string, string, () => ReactNode][] = [
  ['profile', 'Hồ sơ và mục tiêu năng lượng', ProfileSection],
  ['allergen', 'Dị ứng và chế độ ăn', AllergenSection],
  ['favs', '5 món hay ăn', FavsSection],
  ['kitchen', 'Bếp', KitchenSection],
  ['verify-email', 'Xác minh email', VerifyEmailSection],
  ['password', 'Đổi mật khẩu', ChangePasswordSection],
  ['sessions', 'Quản lý phiên đăng nhập', SessionsSection],
  ['mfa', 'Xác thực hai bước (TOTP)', MfaSection],
  ['consent', 'Đồng ý sử dụng dữ liệu', ConsentSection],
  ['export', 'Tải dữ liệu của tôi', ExportSection],
  ['dsr', 'Yêu cầu sửa, hạn chế hoặc phản đối', ManualDsrSection],
  ['delete', 'Xoá tài khoản', DeleteSection],
];
