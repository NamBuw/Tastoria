import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';

import { api, call, isCode, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { useReference } from '@/lib/queries';
import { space } from '@/theme';

import { SLOT_LABEL } from './domain';
import { Button, Card, Chip, ErrorBox, Field, Loading, Notice, Radio, Row, Section, T } from './ui';

// ---- body metrics -------------------------------------------------------------------------------

export type BodyDraft = {
  sex: 'male' | 'female' | null;
  birth_year: string;
  height_cm: string;
  weight_kg: string;
  activity_level: 'light' | 'moderate' | 'heavy' | null;
  goal: 'maintain' | 'lose' | 'expert' | null;
};

export function profileToDraft(p?: Schemas['Profile'] | null): BodyDraft {
  return {
    sex: p?.sex ?? null,
    birth_year: p?.birth_year ? String(p.birth_year) : '',
    height_cm: p?.height_cm ? String(p.height_cm) : '',
    weight_kg: p?.weight_kg ? String(p.weight_kg) : '',
    activity_level: p?.activity_level ?? null,
    goal: p?.goal ?? null,
  };
}

const num = (s: string) => (s.trim() === '' ? null : Number(s.replace(',', '.')));

export function draftToUpdate(d: BodyDraft, adult = false): Schemas['ProfileUpdate'] {
  return {
    sex: d.sex,
    birth_year: num(d.birth_year),
    height_cm: num(d.height_cm),
    weight_kg: num(d.weight_kg),
    activity_level: d.activity_level,
    goal: d.goal,
    ...(adult ? { adult_confirmed: true } : {}),
  };
}

export function BodyFields({
  d,
  set,
  errors,
}: {
  d: BodyDraft;
  set: (p: Partial<BodyDraft>) => void;
  errors: Record<string, string>;
}) {
  return (
    <View style={{ gap: space.md }}>
      <View style={{ gap: space.xs }}>
        <T v="label">Giới</T>
        <Row>
          <Radio label="Nữ" selected={d.sex === 'female'} onPress={() => set({ sex: 'female' })} />
          <Radio label="Nam" selected={d.sex === 'male'} onPress={() => set({ sex: 'male' })} />
        </Row>
        {errors.sex ? <T tone="danger" v="small">{errors.sex}</T> : null}
      </View>
      <Field
        label="Năm sinh"
        testID="body-birth-year"
        value={d.birth_year}
        onChangeText={(v) => set({ birth_year: v.replace(/[^0-9]/g, '') })}
        keyboardType="number-pad"
        inputMode="numeric"
        maxLength={4}
        placeholder="Ví dụ 1995"
        error={errors.birth_year}
      />
      <Row style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }} gap={space.md}>
        <View style={{ flex: 1 }}>
          <Field
            label="Chiều cao (cm)"
            testID="body-height"
            value={d.height_cm}
            onChangeText={(v) => set({ height_cm: v })}
            keyboardType="decimal-pad"
            inputMode="decimal"
            error={errors.height_cm}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Field
            label="Cân nặng (kg)"
            testID="body-weight"
            value={d.weight_kg}
            onChangeText={(v) => set({ weight_kg: v })}
            keyboardType="decimal-pad"
            inputMode="decimal"
            error={errors.weight_kg}
          />
        </View>
      </Row>
    </View>
  );
}

export function ActivityGoalFields({ d, set }: { d: BodyDraft; set: (p: Partial<BodyDraft>) => void }) {
  return (
    <View style={{ gap: space.lg }}>
      <View style={{ gap: space.xs }}>
        <T v="label">Mức vận động</T>
        <View style={{ gap: space.sm }}>
          <Radio label="Nhẹ: ngồi nhiều, ít đi lại" selected={d.activity_level === 'light'} onPress={() => set({ activity_level: 'light' })} />
          <Radio
            label="Trung bình: đi lại, đứng nhiều"
            selected={d.activity_level === 'moderate'}
            onPress={() => set({ activity_level: 'moderate' })}
          />
          <Radio label="Nặng: lao động chân tay, tập nhiều" selected={d.activity_level === 'heavy'} onPress={() => set({ activity_level: 'heavy' })} />
        </View>
      </View>
      <View style={{ gap: space.xs }}>
        <T v="label">Mục tiêu</T>
        <View style={{ gap: space.sm }}>
          <Radio label="Giữ cân" selected={d.goal === 'maintain'} onPress={() => set({ goal: 'maintain' })} />
          <Radio label="Giảm cân" selected={d.goal === 'lose'} onPress={() => set({ goal: 'lose' })} />
          <Radio label="Do chuyên gia dinh dưỡng đặt" selected={d.goal === 'expert'} onPress={() => set({ goal: 'expert' })} />
        </View>
      </View>
    </View>
  );
}

// ---- energy target (UC11) ------------------------------------------------------------------------

/**
 * Suggested target with its formula, or a typed one (user / expert). Writes PUT /me/energy-target only when the
 * person confirms (FR-09-07). Handles the below-floor confirmation (409 below_floor_confirmation_required).
 */
export function EnergyTargetPanel({
  goal,
  onSaved,
  onLater,
}: {
  goal: 'maintain' | 'lose' | 'expert';
  onSaved: (r: Schemas['EnergyTargetResult']) => void;
  onLater?: () => void;
}) {
  const sugg = useQuery({
    queryKey: ['energy-suggestion', goal],
    queryFn: () => call(api.POST('/me/energy-suggestion', { body: { goal: goal as 'maintain' | 'lose' } })),
    enabled: goal !== 'expert',
    staleTime: 0,
  });
  const [typed, setTyped] = useState(goal === 'expert');
  const [kcal, setKcal] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [needFloor, setNeedFloor] = useState(false);

  const save = async (body: Schemas['EnergyTarget']) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await call(api.PUT('/me/energy-target', { body }));
      onSaved(r);
    } catch (e) {
      if (isCode(e, 'below_floor_confirmation_required')) setNeedFloor(true);
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const typedBody = (confirm = false): Schemas['EnergyTarget'] => ({
    kcal_target: Number(kcal),
    kcal_source: goal === 'expert' ? 'expert' : 'user',
    ...(goal === 'expert' ? { goal: 'expert' as const } : {}),
    ...(confirm ? { confirm_below_floor: true } : {}),
  });

  return (
    <View style={{ gap: space.md }}>
      {goal !== 'expert' && !typed ? (
        sugg.isLoading ? (
          <Loading label="Đang tính gợi ý…" />
        ) : sugg.error ? (
          <ErrorBox message={errorText(sugg.error)} onRetry={() => sugg.refetch()} />
        ) : sugg.data ? (
          <Card testID="energy-suggestion">
            <T v="small" tone="muted">
              Mục tiêu gợi ý
            </T>
            <T v="huge">{sugg.data.suggested_kcal.toLocaleString('vi-VN')} kcal/ngày</T>
            <T>
              Bữa trưa khoảng {Math.round(sugg.data.e_lunch_kcal)} kcal, bữa tối khoảng {Math.round(sugg.data.e_dinner_kcal)} kcal.
            </T>
            <T v="small" tone="muted">
              Đây là ước tính, không thay lời khuyên của bác sĩ. Cách tính: {sugg.data.equation ?? 'FAO/WHO/UNU 1985'}; hệ số vận động{' '}
              {String(sugg.data.pal).replace('.', ',')}
              {sugg.data.floor_applied ? '; đã nâng lên mức sàn tối thiểu' : ''}.{sugg.data.source ? ` Nguồn: ${sugg.data.source}.` : ''}
            </T>
          </Card>
        ) : null
      ) : (
        <Field
          label={goal === 'expert' ? 'Mục tiêu chuyên gia đặt (kcal/ngày)' : 'Mục tiêu của bạn (kcal/ngày)'}
          testID="energy-typed"
          value={kcal}
          onChangeText={(v) => setKcal(v.replace(/[^0-9]/g, ''))}
          keyboardType="number-pad"
          inputMode="numeric"
          hint="Từ 800 đến 5.000 kcal."
        />
      )}
      {needFloor ? (
        <Notice tone="warn">
          <T>Mục tiêu này thấp hơn mức sàn khuyến nghị (1.200 kcal với nữ, 1.500 kcal với nam). Vẫn lưu?</T>
          <Button label="Vẫn lưu mục tiêu này" kind="secondary" onPress={() => save(typedBody(true))} loading={busy} />
        </Notice>
      ) : err ? (
        <ErrorBox message={errorText(err)} />
      ) : null}
      {goal !== 'expert' && !typed ? (
        <>
          <Button
            label="Dùng mục tiêu này"
            testID="energy-use"
            loading={busy}
            disabled={!sugg.data}
            onPress={() => sugg.data && save({ kcal_target: sugg.data.suggested_kcal, kcal_source: 'suggested', goal })}
          />
          <Button label="Tự nhập" kind="secondary" onPress={() => setTyped(true)} />
        </>
      ) : (
        <Button
          label="Lưu mục tiêu"
          testID="energy-save-typed"
          loading={busy}
          disabled={!kcal || Number(kcal) < 800 || Number(kcal) > 5000}
          onPress={() => save(typedBody())}
        />
      )}
      {onLater ? <Button label="Để sau" kind="ghost" onPress={onLater} /> : null}
    </View>
  );
}

// ---- allergens + diet ---------------------------------------------------------------------------

export function AllergenDietFields({
  allergens,
  none,
  diet,
  onAllergens,
  onNone,
  onDiet,
  showDiet = true,
}: {
  allergens: string[];
  none: boolean;
  diet: string | null;
  onAllergens: (codes: string[]) => void;
  onNone: (v: boolean) => void;
  onDiet: (code: string | null) => void;
  showDiet?: boolean;
}) {
  const ref = useReference();
  if (ref.isLoading) return <Loading />;
  if (ref.error) return <ErrorBox message={errorText(ref.error)} onRetry={() => ref.refetch()} />;
  const groups = ref.data?.allergen_groups ?? [];
  const toggle = (code: string) => {
    onNone(false);
    onAllergens(allergens.includes(code) ? allergens.filter((x) => x !== code) : [...allergens, code]);
  };
  return (
    <View style={{ gap: space.lg }}>
      <Section title="Nhóm dị ứng">
        <T tone="muted">Món có nguyên liệu, gia vị hoặc đồ thay thế thuộc nhóm đã chọn sẽ không bao giờ được đề xuất.</T>
        <View style={{ gap: space.sm }}>
          {groups.map((g) => (
            <Chip key={g.code} testID={`allergen-${g.code}`} label={g.name_vi} selected={allergens.includes(g.code)} onPress={() => toggle(g.code)} />
          ))}
          <Chip
            testID="allergen-none"
            label="Không dị ứng nhóm nào"
            selected={none}
            onPress={() => {
              onNone(!none);
              if (!none) onAllergens([]);
            }}
          />
        </View>
      </Section>
      {showDiet ? (
        <Section title="Chế độ ăn">
          <View style={{ gap: space.sm }}>
            <Radio label="Không theo chế độ nào" selected={diet === null} onPress={() => onDiet(null)} />
            {(ref.data?.diets ?? []).map((d) => (
              <Radio key={d.code} label={d.name_vi} selected={diet === d.code} onPress={() => onDiet(d.code)} />
            ))}
          </View>
        </Section>
      ) : null}
    </View>
  );
}

// ---- favourites ---------------------------------------------------------------------------------

export function FavoritesPicker({ selected, onChange }: { selected: string[]; onChange: (ids: string[]) => void }) {
  const [q, setQ] = useState('');
  const recipes = useQuery({
    queryKey: ['recipes', q],
    queryFn: () => call(api.GET('/recipes', { params: { query: { q: q || undefined, limit: 100 } } })),
  });
  const items = recipes.data?.items ?? [];
  const bySlot = (['man', 'rau', 'canh'] as const).map((s) => ({ slot: s, list: items.filter((r) => r.slot === s) }));
  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : selected.length >= 5 ? selected : [...selected, id]);
  return (
    <View style={{ gap: space.md }}>
      <T accessibilityLiveRegion="polite">Đã chọn {selected.length}/5 món.</T>
      <Field label="Tìm món" value={q} onChangeText={setQ} placeholder="Ví dụ: canh chua" />
      {recipes.isLoading ? <Loading /> : null}
      {recipes.error ? <ErrorBox message={errorText(recipes.error)} onRetry={() => recipes.refetch()} /> : null}
      {bySlot.map(({ slot, list }) =>
        list.length ? (
          <Section key={slot} title={`Món ${SLOT_LABEL[slot].toLowerCase()}`}>
            <Row>
              {list.map((r) => (
                <Chip
                  key={r.id}
                  testID={`fav-${r.id}`}
                  label={r.name_vi}
                  selected={selected.includes(r.id)}
                  disabled={!selected.includes(r.id) && selected.length >= 5}
                  onPress={() => toggle(r.id)}
                />
              ))}
            </Row>
          </Section>
        ) : null,
      )}
    </View>
  );
}
