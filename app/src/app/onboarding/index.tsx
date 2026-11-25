import { useQueries, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState } from 'react';

import { api, call, isCode } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { BrandHeader } from '@/components/Brand';
import { PolicyCard } from '@/components/PolicyCard';
import { Button, ErrorBox, Loading, Screen, T } from '@/components/ui';
import { saveProgress } from '@/lib/onboarding';
import { qk } from '@/lib/queries';

const PURPOSES = ['health_profile', 'personalization', 'photo_contribution'] as const;

/** Separate consent screen before step 1 of "Hồ sơ 60 giây": nothing ticked, skip allowed (UC09 1–3, FR-09-01). */
export default function ConsentStep() {
  const router = useRouter();
  const qc = useQueryClient();
  const { user } = useSession();
  const policies = useQueries({
    queries: PURPOSES.map((p) => ({
      queryKey: ['policy', p],
      queryFn: () => call(api.GET('/policies/{purpose}/current', { params: { path: { purpose: p } } })),
      staleTime: 0,
    })),
  });
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const loading = policies.some((q) => q.isLoading);
  const failed = policies.find((q) => q.error);

  const submit = async (skip: boolean) => {
    if (!user) return;
    setBusy(true);
    setErr(null);
    try {
      const decisions = skip
        ? []
        : policies
            .map((q) => q.data)
            .filter((p): p is NonNullable<typeof p> => !!p && !!checked[p.purpose_code])
            .map((p) => ({ policy_version_id: p.id, action: 'grant' as const }));
      if (decisions.length) {
        await call(api.POST('/me/consents', { body: { channel: 'onboarding', decisions } }));
      }
      await qc.invalidateQueries({ queryKey: qk.consents });
      await saveProgress(user.id, { consent: true, step: 0 });
      router.replace('/onboarding/ho-so');
    } catch (e) {
      if (isCode(e, 'policy_outdated')) policies.forEach((q) => q.refetch());
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen
      testID="screen-consent"
      variant="focused"
      footer={
        <>
          <Button label="Tiếp tục" testID="consent-continue" onPress={() => submit(false)} loading={busy} disabled={loading || !!failed} />
          <Button
            label="Dùng thử ngay, thiết lập sau →"
            kind="ghost"
            testID="onboarding-skip-all"
            onPress={async () => {
              if (!user) return;
              await saveProgress(user.id, { consent: true, done: true });
              router.replace('/bep');
            }}
            disabled={busy}
          />
          <Button label="Không tích mục nào, sang bước tiếp" kind="ghost" testID="consent-skip" onPress={() => submit(true)} disabled={busy || loading} />
        </>
      }>
      <BrandHeader subtitle="Thiết lập nhanh (không bắt buộc)" />
      <T v="h2" accessibilityRole="header">
        Bạn có muốn bật các tuỳ chọn hỗ trợ sau không?
      </T>
      <T tone="muted">
        Không chọn mục nào bạn vẫn chụp ảnh tủ lạnh, tính calo và xem công thức bình thường. Thay đổi bất cứ lúc nào trong Cài đặt.
      </T>
      {loading ? <Loading label="Đang tải điều khoản…" /> : null}
      {failed ? (
        <ErrorBox message={`Không tải được điều khoản. ${errorText(failed.error)}`} onRetry={() => policies.forEach((q) => q.refetch())} />
      ) : null}
      {policies.map((q) =>
        q.data ? (
          <PolicyCard
            key={q.data.id}
            policy={q.data}
            checked={!!checked[q.data.purpose_code]}
            onChange={(v) => setChecked((s) => ({ ...s, [q.data!.purpose_code]: v }))}
          />
        ) : null,
      )}
      {err ? <ErrorBox message={errorText(err)} /> : null}
    </Screen>
  );
}
