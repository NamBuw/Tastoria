import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useEffect, useState, type ReactNode } from 'react';
import { Platform, Pressable, View } from 'react-native';

import { api, API_URL, ApiError, call, refreshSession, type Schemas } from '@/api/client';
import { errorText, fieldErrors } from '@/api/errors';
import { useSession } from '@/auth/session';
import { PolicyCard } from '@/components/PolicyCard';
import {
  ActivityGoalFields,
  AllergenDietFields,
  BodyFields,
  draftToUpdate,
  EnergyTargetPanel,
  FavoritesPicker,
  profileToDraft,
  type BodyDraft,
} from '@/components/profileForms';
import { Button, Card, ErrorBox, Field, Loading, Notice, Row, Screen, Stepper, T } from '@/components/ui';
import { qk, useConsents, useProfile, useSettings } from '@/lib/queries';
import { space, TOUCH, useTheme } from '@/theme';

/** Cài đặt (UC03, UC05–UC07, UC10, UC11). */
export default function Settings() {
  const { user, signOut } = useSession();
  const router = useRouter();
  const [open, setOpen] = useState<string | null>(null);
  const toggle = (k: string) => setOpen(open === k ? null : k);
  return (
    <Screen testID="screen-settings">
      <T tone="muted">Đăng nhập bằng {user?.email}</T>
      <Group k="profile" title="Hồ sơ và mục tiêu năng lượng" open={open} toggle={toggle}>
        <ProfileSection />
      </Group>
      <Group k="allergen" title="Dị ứng và chế độ ăn" open={open} toggle={toggle}>
        <AllergenSection />
      </Group>
      <Group k="favs" title="5 món hay ăn" open={open} toggle={toggle}>
        <FavsSection />
      </Group>
      <Group k="kitchen" title="Bếp" open={open} toggle={toggle}>
        <KitchenSection />
      </Group>
      <Group k="consent" title="Đồng ý sử dụng dữ liệu" open={open} toggle={toggle}>
        <ConsentSection />
      </Group>
      <Group k="export" title="Tải dữ liệu của tôi" open={open} toggle={toggle}>
        <ExportSection />
      </Group>
      <Group k="delete" title="Xoá tài khoản" open={open} toggle={toggle}>
        <DeleteSection />
      </Group>
      <Button label="Làm khảo sát gu món ăn" kind="secondary" onPress={() => router.push('/khao-sat')} />
      <Button label="Đăng xuất" kind="secondary" testID="sign-out" onPress={() => signOut(false)} />
      <Button label="Đăng xuất mọi thiết bị" kind="ghost" onPress={() => signOut(true)} />
    </Screen>
  );
}

function Group({ k, title, open, toggle, children }: { k: string; title: string; open: string | null; toggle: (k: string) => void; children: ReactNode }) {
  const { c } = useTheme();
  const isOpen = open === k;
  return (
    <Card style={{ padding: 0, gap: 0 }}>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: isOpen }}
        testID={`settings-${k}`}
        onPress={() => toggle(k)}
        style={{ minHeight: TOUCH + 8, paddingHorizontal: space.lg, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <T v="title">{title}</T>
        <T v="title" style={{ color: c.accent }}>
          {isOpen ? '−' : '+'}
        </T>
      </Pressable>
      {isOpen ? <View style={{ paddingHorizontal: space.lg, paddingBottom: space.lg, gap: space.md }}>{children}</View> : null}
    </Card>
  );
}

function ProfileSection() {
  const qc = useQueryClient();
  const profile = useProfile();
  const [draft, setDraft] = useState<BodyDraft | null>(null);
  const [saved, setSaved] = useState(false);
  const [target, setTarget] = useState(false);
  useEffect(() => {
    if (profile.data && !draft) setDraft(profileToDraft(profile.data));
  }, [profile.data, draft]);
  const save = useMutation({
    mutationFn: (adult: boolean) => call(api.PUT('/me/profile', { body: draftToUpdate(draft!, adult) })),
    onSuccess: () => {
      setSaved(true);
      qc.invalidateQueries({ queryKey: qk.profile });
    },
  });
  if (profile.isLoading || !draft) return <Loading />;
  if (profile.error) return <ErrorBox message={errorText(profile.error)} />;
  const p = profile.data!;
  if (!p.health_profile_consented) {
    return (
      <Notice>
        <T>Bạn chưa đồng ý lưu hồ sơ sức khoẻ nên Tastoria chưa tính mục tiêu năng lượng. Bật trong mục "Đồng ý sử dụng dữ liệu".</T>
      </Notice>
    );
  }
  const set = (x: Partial<BodyDraft>) => {
    setSaved(false);
    setDraft((d) => ({ ...d!, ...x }));
  };
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
      <BodyFields d={draft} set={set} errors={fieldErrors(save.error)} />
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
      <Button label="Lưu hồ sơ" onPress={() => save.mutate(false)} loading={save.isPending} />
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

function AllergenSection() {
  const qc = useQueryClient();
  const profile = useProfile();
  const [a, setA] = useState<string[] | null>(null);
  const [none, setNone] = useState(false);
  const [diet, setDiet] = useState<string | null>(null);
  useEffect(() => {
    if (profile.data && a === null) {
      setA(profile.data.allergen_codes);
      setNone(profile.data.allergen_codes.length === 0);
      setDiet(profile.data.diet_code);
    }
  }, [profile.data, a]);
  const save = useMutation({
    mutationFn: async () => {
      await call(api.PUT('/me/allergens', { body: { allergen_codes: none ? [] : a ?? [] } }));
      await call(api.PUT('/me/diet', { body: { diet_code: diet } }));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.profile }),
  });
  if (a === null) return <Loading />;
  return (
    <View style={{ gap: space.md }}>
      <AllergenDietFields allergens={a} none={none} diet={diet} onAllergens={setA} onNone={setNone} onDiet={setDiet} />
      {save.error ? <ErrorBox message={errorText(save.error)} /> : null}
      {save.isSuccess ? <T tone="muted">Đã lưu.</T> : null}
      <Button label="Lưu" onPress={() => save.mutate()} loading={save.isPending} disabled={!none && !a.length} />
    </View>
  );
}

function FavsSection() {
  const qc = useQueryClient();
  const profile = useProfile();
  const [ids, setIds] = useState<string[] | null>(null);
  useEffect(() => {
    if (profile.data && ids === null) setIds(profile.data.favorite_recipe_ids);
  }, [profile.data, ids]);
  const save = useMutation({
    mutationFn: () => call(api.PUT('/me/favorites', { body: { recipe_ids: ids ?? [] } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.profile }),
  });
  if (ids === null) return <Loading />;
  return (
    <View style={{ gap: space.md }}>
      <FavoritesPicker selected={ids} onChange={setIds} />
      {save.error ? <ErrorBox message={errorText(save.error)} /> : null}
      {save.isSuccess ? <T tone="muted">Đã lưu.</T> : null}
      <Button label="Lưu" onPress={() => save.mutate()} loading={save.isPending} />
    </View>
  );
}

function KitchenSection() {
  const qc = useQueryClient();
  const settings = useSettings();
  const [s, setS] = useState<Schemas['UserSettings'] | null>(null);
  useEffect(() => {
    if (settings.data && !s) setS(settings.data);
  }, [settings.data, s]);
  const save = useMutation({
    mutationFn: () =>
      call(api.PUT('/me/settings', { body: { burners: s!.burners, default_persons: s!.default_persons, timezone: s!.timezone } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.settings }),
  });
  if (!s) return <Loading />;
  return (
    <View style={{ gap: space.md }}>
      <Stepper label="Số họng bếp" value={s.burners} min={1} max={4} onChange={(v) => setS({ ...s, burners: v })} />
      <Stepper label="Số người ăn mặc định" value={s.default_persons} min={1} max={6} onChange={(v) => setS({ ...s, default_persons: v })} />
      <T v="small" tone="muted">
        Múi giờ: {s.timezone}
      </T>
      {save.error ? <ErrorBox message={errorText(save.error)} /> : null}
      {save.isSuccess ? <T tone="muted">Đã lưu.</T> : null}
      <Button label="Lưu" onPress={() => save.mutate()} loading={save.isPending} />
    </View>
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
  return (
    <View style={{ gap: space.md }}>
      <T tone="muted">
        Rút đồng ý "Cá nhân hoá" xoá lịch sử tương tác dùng để học gu; rút "Hồ sơ sức khoẻ" xoá chỉ số cơ thể. Việc xoá hoàn tất trong 24
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
            <PolicyCard policy={p} checked={granted && !outdated} onChange={(v) => change.mutate({ policy: p, grant: v })} />
            {outdated ? <T v="small" tone="danger">Điều khoản đã có bản mới; tích lại để đồng ý bản mới.</T> : null}
          </View>
        );
      })}
      {change.error ? <ErrorBox message={errorText(change.error)} /> : null}
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
    refetchInterval: (q) => (q.state.data?.status === 'completed' ? false : 3000),
  });
  const download = async () => {
    setDlErr(null);
    const r = await api.GET('/me/data-requests/{id}/download', { params: { path: { id: reqId! } }, parseAs: 'blob' });
    if (!r.response.ok || !r.data) {
      setDlErr(errorText(new ApiError(r.response.status, (r.error as never) ?? null)));
      return;
    }
    if (Platform.OS === 'web') {
      const url = URL.createObjectURL(r.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'tastoria-du-lieu.zip';
      a.click();
      URL.revokeObjectURL(url);
    } else {
      setDlErr(`Tệp đã sẵn sàng. Bản Android chưa lưu tệp được; tải trên bản web tại ${API_URL || 'trang Tastoria'}.`);
    }
  };
  const d = status.data;
  return (
    <View style={{ gap: space.md }}>
      <T tone="muted">Tệp ZIP chứa dữ liệu cá nhân Tastoria đang lưu về bạn. Chậm nhất 24 giờ sau khi gửi yêu cầu.</T>
      {d ? (
        <T>
          Trạng thái: {d.status === 'completed' ? 'đã xong' : d.status === 'received' ? 'đã nhận' : d.status}
          {d.status !== 'completed' ? ` · hạn ${new Date(d.due_at).toLocaleString('vi-VN')}` : ''}
        </T>
      ) : null}
      {create.error ? <ErrorBox message={errorText(create.error)} /> : null}
      {dlErr ? <Notice tone="warn"><T>{dlErr}</T></Notice> : null}
      {d?.download_available ? (
        <Button label="Tải tệp" onPress={download} />
      ) : (
        <Button label="Gửi yêu cầu tải dữ liệu" onPress={() => create.mutate()} loading={create.isPending} disabled={!!reqId} />
      )}
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
