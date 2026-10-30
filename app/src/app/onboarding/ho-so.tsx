import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { api, call, isCode } from '@/api/client';
import { errorText, fieldErrors } from '@/api/errors';
import { useSession } from '@/auth/session';
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
import { Button, ErrorBox, Loading, Notice, ProgressDots, Screen, T } from '@/components/ui';
import { getProgress, saveProgress } from '@/lib/onboarding';
import { qk, useConsents, useProfile } from '@/lib/queries';

type StepId = 'body' | 'activity' | 'allergen' | 'favorites';
const LABEL: Record<StepId, string> = {
  body: 'Cơ thể',
  activity: 'Vận động và mục tiêu',
  allergen: 'Dị ứng và chế độ ăn',
  favorites: '5 món hay ăn',
};

/** "Hồ sơ 60 giây": 4 steps with health consent, 2 without (UC09, FR-09-03). */
export default function ProfileSteps() {
  const router = useRouter();
  const qc = useQueryClient();
  const { user } = useSession();
  const consents = useConsents();
  const profile = useProfile();
  const health = consents.data?.items.some((c) => c.purpose_code === 'health_profile' && c.state === 'granted') ?? false;
  const steps: StepId[] = useMemo(() => (health ? ['body', 'activity', 'allergen', 'favorites'] : ['allergen', 'favorites']), [health]);

  const [idx, setIdx] = useState<number | null>(null);
  const [draft, setDraft] = useState<BodyDraft>(profileToDraft(null));
  const [energyFor, setEnergyFor] = useState<'maintain' | 'lose' | 'expert' | null>(null);
  const [askAdult, setAskAdult] = useState(false);
  const [minor, setMinor] = useState(false);
  const [allergens, setAllergens] = useState<string[]>([]);
  const [none, setNone] = useState(false);
  const [diet, setDiet] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  // resume at the first step the server has not confirmed (FR-09-12)
  useEffect(() => {
    if (!user || consents.isLoading || profile.isLoading || idx !== null) return;
    let cancelled = false;
    getProgress(user.id).then((p) => {
      if (cancelled) return;
      if (profile.data) {
        setDraft(profileToDraft(profile.data));
        setAllergens(profile.data.allergen_codes);
        setDiet(profile.data.diet_code);
        setFavs(profile.data.favorite_recipe_ids);
      }
      setIdx(Math.min(p.step, steps.length - 1));
    });
    return () => { cancelled = true; };
  }, [user, consents.isLoading, profile.isLoading, profile.data, idx, steps.length]);

  if (idx === null) return <Screen><Loading /></Screen>;
  const step = steps[idx];
  const set = (p: Partial<BodyDraft>) => setDraft((d) => ({ ...d, ...p }));

  const advance = async () => {
    const next = idx + 1;
    if (user) await saveProgress(user.id, { step: next });
    setErr(null);
    if (next >= steps.length) {
      if (user) await saveProgress(user.id, { done: true });
      await qc.invalidateQueries({ queryKey: qk.profile });
      router.replace('/bep');
    } else setIdx(next);
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const saveBody = (adult = false) =>
    run(async () => {
      try {
        await call(api.PUT('/me/profile', { body: draftToUpdate(draft, adult) }));
        setAskAdult(false);
        if (draft.goal) setEnergyFor(draft.goal);
        else await advance();
      } catch (e) {
        if (isCode(e, 'age_confirmation_required')) setAskAdult(true);
        else if (isCode(e, 'age_below_minimum')) setMinor(true);
        else if (isCode(e, 'consent_required')) router.replace('/onboarding');
        else if (isCode(e, 'validation_error') && Object.keys(fieldErrors(e)).some((k) => k !== 'activity_level' && k !== 'goal')) {
          setIdx(0);
          throw e;
        } else throw e;
      }
    });

  const saveAllergens = () =>
    run(async () => {
      await call(api.PUT('/me/allergens', { body: { allergen_codes: none ? [] : allergens } }));
      await call(api.PUT('/me/diet', { body: { diet_code: diet } }));
      await advance();
    });

  const saveFavs = (ids: string[]) =>
    run(async () => {
      await call(api.PUT('/me/favorites', { body: { recipe_ids: ids } }));
      await advance();
    });

  const fe = fieldErrors(err);
  const bodyOk = draft.sex && draft.birth_year.length === 4 && draft.height_cm && draft.weight_kg;

  let content: ReactNode = null;
  let footer: ReactNode = null;
  if (step === 'body') {
    content = (
      <>
        <T tone="muted">Dùng để ước tính năng lượng mỗi bữa. Lưu mã hoá, chỉ dùng cho mục đích bạn đã đồng ý.</T>
        <BodyFields d={draft} set={set} errors={fe} />
      </>
    );
    footer = <Button label="Tiếp" testID="step-next" disabled={!bodyOk} onPress={() => setIdx(1)} />;
  } else if (step === 'activity') {
    if (minor) {
      content = (
        <Notice tone="warn">
          <T>Tastoria chỉ tính mục tiêu năng lượng cho người từ 18 tuổi. Bạn vẫn dùng được quét và ghép mâm; mâm sẽ không bám mục tiêu calo.</T>
        </Notice>
      );
      footer = <Button label="Tiếp" onPress={() => setIdx(idx + 1)} />;
    } else if (energyFor) {
      content = (
        <EnergyTargetPanel
          goal={energyFor}
          onSaved={() => void advance()}
          onLater={() => void advance()}
        />
      );
    } else if (askAdult) {
      content = (
        <Notice>
          <T v="title">Bạn đã đủ 18 tuổi chưa?</T>
          <T>Theo năm sinh, bạn có thể mới 17 tuổi. Tastoria chỉ tính mục tiêu năng lượng cho người từ 18 tuổi.</T>
          <Button label="Tôi đã đủ 18 tuổi" onPress={() => saveBody(true)} loading={busy} />
          <Button
            label="Chưa"
            kind="secondary"
            onPress={() => {
              setAskAdult(false);
              setMinor(true);
            }}
          />
        </Notice>
      );
    } else {
      content = <ActivityGoalFields d={draft} set={set} />;
      footer = (
        <>
          <Button label="Tiếp" testID="step-next" loading={busy} disabled={!draft.activity_level || !draft.goal} onPress={() => saveBody()} />
          <Button label="Quay lại" kind="ghost" onPress={() => setIdx(0)} />
        </>
      );
    }
  } else if (step === 'allergen') {
    content = (
      <>
        {!health ? (
          <Notice>
            <T>Chưa có mục tiêu năng lượng vì bạn chưa đồng ý lưu hồ sơ sức khoẻ. Mâm vẫn được ghép, chỉ không bám calo.</T>
          </Notice>
        ) : null}
        <AllergenDietFields allergens={allergens} none={none} diet={diet} onAllergens={setAllergens} onNone={setNone} onDiet={setDiet} />
      </>
    );
    footer = (
      <>
        {!none && allergens.length === 0 ? (
          <T v="small" tone="muted">
            Chọn ít nhất một nhóm, hoặc chọn &quot;Không dị ứng nhóm nào&quot;.
          </T>
        ) : null}
        <Button label="Tiếp" testID="step-next" loading={busy} disabled={!none && allergens.length === 0} onPress={saveAllergens} />
      </>
    );
  } else {
    content = (
      <>
        <T tone="muted">Chọn tối đa 5 món nhà bạn hay ăn. Tastoria dùng chúng để đoán gu lúc đầu.</T>
        <FavoritesPicker selected={favs} onChange={setFavs} />
      </>
    );
    footer = (
      <>
        <Button label="Xong" testID="step-done" loading={busy} onPress={() => saveFavs(favs)} />
        <Button label="Bỏ qua" kind="ghost" testID="step-skip" onPress={() => saveFavs([])} />
      </>
    );
  }

  return (
    <Screen testID={`screen-onboarding-${step}`} footer={footer}>
      <ProgressDots step={idx + 1} total={steps.length} label={LABEL[step]} />
      <T v="h1" accessibilityRole="header">
        {step === 'activity' && energyFor ? 'Mục tiêu năng lượng' : LABEL[step]}
      </T>
      {content}
      {err && !askAdult ? <ErrorBox message={errorText(err)} /> : null}
    </Screen>
  );
}
