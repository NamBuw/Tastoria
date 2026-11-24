import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { api, ApiError, call, isCode, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { recipePhotoFor } from '@/components/Brand';
import { fmtBowls, FreshBadge, Icon, KcalBar, SLOT_LABEL } from '@/components/domain';
import { BroadsheetLedgerFrame, Button, Card, Chip, ErrorBox, Loading, Notice, Row, Screen, Section, Segmented, Sheet, Stepper, T } from '@/components/ui';
import { useIdempotencyKey } from '@/lib/idempotency';
import { currentMeal, MEAL_LABEL, qk, useLatestPlan, useLots, useReference, useSettings } from '@/lib/queries';
import { font, radius, space, useLayout, useTheme } from '@/theme';

type Plan = Schemas['MealPlan'];
type Item = Schemas['MealPlanItem'];
type Meal = 'lunch' | 'dinner';

const SWAP_REASONS = [
  { v: 'khong_hop_gu', l: 'Không hợp gu' },
  { v: 'moi_an', l: 'Mới ăn gần đây' },
  { v: 'thieu_thoi_gian', l: 'Không đủ thời gian nấu' },
  { v: 'khac', l: 'Lý do khác' },
] as const;

const SLOT_ORDER = { man: 0, rau: 1, canh: 2 } as const;

function shouldResetIdemOnError(e: unknown): boolean {
  return e instanceof ApiError && e.status >= 400 && e.status < 500 && !isCode(e, 'idempotency_in_progress');
}

/** Mâm cơm hôm nay (UC15–UC18 entry points). */
export default function TrayScreen() {
  const [meal, setMeal] = useState<Meal>(currentMeal());
  const latest = useLatestPlan(meal);
  const [composing, setComposing] = useState(false);
  const plan = latest.data;

  return (
    <Screen testID="screen-tray" scrollKey={plan && !composing ? plan.id : `new-${meal}`}>
      <MealSwitch meal={meal} onChange={setMeal} />
      {latest.isLoading ? <Loading /> : null}
      {latest.error ? <ErrorBox message={errorText(latest.error)} onRetry={() => latest.refetch()} /> : null}
      {plan && !composing ? (
        <PlanView key={plan.id} plan={plan} onNew={() => setComposing(true)} />
      ) : latest.isSuccess ? (
        <Composer key={meal} meal={meal} defaultPersons={plan?.persons} onDone={() => setComposing(false)} onCancel={plan ? () => setComposing(false) : undefined} />
      ) : null}
    </Screen>
  );
}

function MealSwitch({ meal, onChange }: { meal: Meal; onChange: (m: Meal) => void }) {
  const { c } = useTheme();
  return (
    <View
      testID="MealSwitch"
      accessibilityRole="radiogroup"
      style={{
        flexDirection: 'row',
        borderBottomWidth: 1,
        borderBottomColor: c.hairline,
        gap: space.xl,
      }}>
      {(['lunch', 'dinner'] as const).map((m) => {
        const on = meal === m;
        return (
          <Pressable
            key={m}
            accessibilityRole="radio"
            accessibilityState={{ selected: on, checked: on }}
            onPress={() => onChange(m)}
            style={{
              minHeight: 44,
              paddingVertical: space.sm,
              paddingHorizontal: 2,
              justifyContent: 'center',
              borderBottomWidth: 2,
              borderBottomColor: on ? c.accent : 'transparent',
              marginBottom: -1,
            }}>
            <T v={on ? 'label' : 'body'} style={{ color: on ? c.text : c.muted }}>
              {MEAL_LABEL[m]}
            </T>
          </Pressable>
        );
      })}
    </View>
  );
}

// ---- composer -----------------------------------------------------------------------------------

function useCreatePlan(meal: Meal, onDone?: () => void) {
  const qc = useQueryClient();
  const idem = useIdempotencyKey();
  return useMutation({
    mutationFn: (body: Schemas['MealPlanCreate']) =>
      call(api.POST('/meal-plans', { body, params: { header: { 'Idempotency-Key': idem.keyFor(body) } } })),
    onSuccess: (p) => {
      idem.reset();
      qc.setQueryData(qk.latestPlan(meal), p);
      qc.invalidateQueries({ queryKey: ['plan'] });
      onDone?.();
    },
    onError: (e) => {
      if (shouldResetIdemOnError(e)) idem.reset();
    },
  });
}

function Composer({
  meal,
  defaultPersons,
  onDone,
  onCancel,
}: {
  meal: Meal;
  defaultPersons?: number;
  onDone: () => void;
  onCancel?: () => void;
}) {
  const { c } = useTheme();
  const settings = useSettings();
  const ref = useReference();
  const lots = useLots();
  const create = useCreatePlan(meal, onDone);
  const [persons, setPersons] = useState<number | null>(defaultPersons ?? null);
  const [minutes, setMinutes] = useState(60);
  const [coeater, setCoeater] = useState<string[]>([]);
  const [pins, setPins] = useState<string[]>([]);
  const n = persons ?? settings.data?.default_persons ?? 2;

  const pinnable = (lots.data?.items ?? []).filter((l) => l.available);
  const err = create.error;
  const shortfalls = err instanceof ApiError ? ((err.problem?.shortfalls as Schemas['TrayShortfall'][] | undefined) ?? []) : [];
  const unmetPins = err instanceof ApiError ? ((err.problem?.unmet_pinned_lot_ids as string[] | undefined) ?? []) : [];

  return (
    <View style={{ gap: space.lg }}>
      <View style={{ gap: 2 }}>
        <T v="huge" accessibilityRole="header">
          Ghép mâm {MEAL_LABEL[meal].toLowerCase()}
        </T>
        <T tone="muted">
          Tự chọn từ đồ đang có trong tủ, ưu tiên đồ gần hết hạn và cân đối 1 món mặn, 1 món rau, 1 món canh.
        </T>
      </View>

      <Card style={{ gap: space.lg }}>
        <Stepper label="Số người ăn" value={n} onChange={setPersons} min={1} max={6} testID="persons" />
        <Segmented label="Thời gian nấu tối đa" options={[30, 45, 60, 90, 120].map((m) => [m, `${m} phút`] as const)} value={minutes} onChange={setMinutes} />
      </Card>

      <View style={{ borderTopWidth: 1, borderTopColor: c.hairline, paddingTop: space.lg, gap: space.lg }}>
        <Section title="Người ăn cùng dị ứng (bữa này)">
          <T v="small" tone="muted">
            Dị ứng của bạn đã được loại trừ sẵn. Chọn thêm nhóm dị ứng của người ăn cùng trong bữa này nếu có.
          </T>
          <Row>
            {(ref.data?.allergen_groups ?? []).map((g) => (
              <Chip
                key={g.code}
                label={g.name_vi.replace(/ \(.*\)$/, '')}
                selected={coeater.includes(g.code)}
                onPress={() => setCoeater((s) => (s.includes(g.code) ? s.filter((x) => x !== g.code) : [...s, g.code]))}
              />
            ))}
          </Row>
        </Section>

        {pinnable.length ? (
          <Section title="Phải dùng trong bữa này (tối đa 2)">
            <Row>
              {pinnable.slice(0, 12).map((l) => (
                <Chip
                  key={l.id}
                  label={l.ingredient_name_vi}
                  left={<FreshBadge value={l.freshness_label} small />}
                  selected={pins.includes(l.id)}
                  disabled={!pins.includes(l.id) && pins.length >= 2}
                  onPress={() => setPins((s) => (s.includes(l.id) ? s.filter((x) => x !== l.id) : [...s, l.id]))}
                />
              ))}
            </Row>
          </Section>
        ) : null}
      </View>

      {isCode(err, 'no_feasible_tray') ? (
        <NoTray shortfalls={shortfalls} />
      ) : isCode(err, 'pin_unsatisfiable') ? (
        <Notice tone="warn">
          <T>{errorText(err)}</T>
          <Button
            label="Bỏ ghim đồ gây vướng"
            kind="secondary"
            onPress={() => setPins((s) => s.filter((x) => !unmetPins.includes(x)))}
          />
        </Notice>
      ) : err ? (
        <ErrorBox message={errorText(err)} />
      ) : null}
      <Button
        label="Ra mâm"
        testID="make-plan"
        onPress={() =>
          create.mutate({ meal, persons: n, max_minutes: minutes, coeater_allergen_codes: coeater, pinned_lot_ids: pins })
        }
        loading={create.isPending}
      />
      {create.isPending ? <T tone="muted">Đang ghép mâm…</T> : null}
      {onCancel ? <Button label="Giữ mâm đang có" kind="ghost" onPress={onCancel} /> : null}
    </View>
  );
}

function NoTray({ shortfalls }: { shortfalls: Schemas['TrayShortfall'][] }) {
  return (
    <Notice tone="warn">
      <T v="title">Chưa ghép được mâm từ đồ đang có</T>
      <T>Mâm gần được nhất còn thiếu:</T>
      {shortfalls.map((s) => (
        <View key={s.rank} style={{ gap: space.xs }}>
          <T v="label">Phương án {s.rank}</T>
          {s.missing.map((m) => (
            <ShoppingRow key={m.ingredient_id} ingredientId={m.ingredient_id} name={m.name_vi} needG={m.need_g} haveG={m.available_g_min} />
          ))}
        </View>
      ))}
      {!shortfalls.length ? <T>Thêm đồ vào Kho hoặc tăng thời gian nấu rồi thử lại.</T> : null}
    </Notice>
  );
}

function ShoppingRow({
  ingredientId,
  name,
  needG,
  haveG,
  itemId,
}: {
  ingredientId: string;
  name: string;
  needG: number;
  haveG: number;
  itemId?: string;
}) {
  const { c } = useTheme();
  const qc = useQueryClient();
  const add = useMutation({
    mutationFn: () =>
      call(
        api.POST('/shopping-items', {
          body: {
            ingredient_id: ingredientId,
            qty_g: Math.max(1, Math.round(needG - haveG)),
            source_meal_plan_item_id: itemId ?? null,
          },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.shopping }),
  });
  return (
    <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
      <View style={{ flexShrink: 1 }}>
        <T>{name}</T>
        <T v="small" tone="muted" tabular>
          cần {Math.round(needG)} g, đang có {Math.round(haveG)} g
        </T>
      </View>
      {add.isSuccess ? (
        <Row gap={space.xs} style={{ flexWrap: 'nowrap' }}>
          <Icon name="check" size={16} color={c.herb} />
          <T v="label" tone="herb">
            Đã thêm
          </T>
        </Row>
      ) : (
        <Button label="Thêm vào đi chợ" kind="secondary" onPress={() => add.mutate()} loading={add.isPending} testID={`shop-add-${name}`} />
      )}
    </Row>
  );
}

// ---- plan view ----------------------------------------------------------------------------------

function PlanView({ plan, onNew }: { plan: Plan; onNew: () => void }) {
  const { c } = useTheme();
  const { isDesktop } = useLayout();
  const router = useRouter();
  const qc = useQueryClient();
  const [dish, setDish] = useState<Item | null>(null);
  const [mode, setMode] = useState<'menu' | 'swap' | 'missing'>('menu');
  const [serveIn, setServeIn] = useState(0);
  const [overTime, setOverTime] = useState<{ over: number; makespan: number } | null>(null);
  const swapKey = useIdempotencyKey();
  const cookKey = useIdempotencyKey();
  const active = plan.items.filter((i) => i.status === 'active');
  const ordered = [...active].sort((a, b) => SLOT_ORDER[a.slot] - SLOT_ORDER[b.slot]);
  const swappedOut = plan.items.filter((i) => i.status === 'swapped_out');
  const lots = useLots();
  const [persons, setPersons] = useState(plan.persons);
  const regroup = useCreatePlan(plan.meal);

  const refresh = (p?: Plan) => {
    if (p) qc.setQueryData(qk.latestPlan(plan.meal), p);
    qc.invalidateQueries({ queryKey: ['plan'] });
  };

  const swap = useMutation({
    mutationFn: async (reason: Schemas['SwapRequest']['swap_reason']) => {
      const body = { swap_reason: reason };
      const key = swapKey.keyFor({ item: dish!.id, body });
      return call(
        api.POST('/meal-plans/{id}/items/{itemId}/swap', {
          params: { path: { id: plan.id, itemId: dish!.id }, header: { 'Idempotency-Key': key } },
          body,
        }),
      );
    },
    onSuccess: (p) => {
      swapKey.reset();
      refresh(p);
      setDish(null);
    },
    onError: (e) => {
      if (isCode(e, 'conflict_state')) refresh();
      if (shouldResetIdemOnError(e)) swapKey.reset();
    },
  });

  const cook = useMutation({
    mutationFn: async (confirmOver: boolean) => {
      if (plan.status === 'proposed') {
        const accepted = await call(api.POST('/meal-plans/{id}/accept', { params: { path: { id: plan.id } } }));
        refresh(accepted);
      }
      const serveAt = new Date(Date.now() + serveIn * 60_000).toISOString();
      const body: Schemas['CookSessionCreate'] = {
        meal_plan_id: plan.id,
        serve_at: serveAt,
        ...(confirmOver ? { confirm_over_time: true } : {}),
      };
      const key = cookKey.keyFor({ ...body, serve_at: serveIn });
      return call(api.POST('/cook-sessions', { body, params: { header: { 'Idempotency-Key': key } } }));
    },
    onSuccess: (s) => {
      cookKey.reset();
      setOverTime(null);
      router.push({ pathname: '/nau/[id]', params: { id: s.id } });
    },
    onError: (e) => {
      if (isCode(e, 'cook_session_in_progress') && typeof e.problem?.cook_session_id === 'string') {
        cookKey.reset();
        router.push({ pathname: '/nau/[id]', params: { id: e.problem.cook_session_id } });
      } else if (isCode(e, 'conflict_state') && typeof e.problem?.over_time_minutes === 'number') {
        cookKey.reset();
        setOverTime({ over: e.problem.over_time_minutes, makespan: Number(e.problem.makespan_s ?? 0) / 60 });
      } else if (shouldResetIdemOnError(e)) {
        cookKey.reset();
      }
    },
  });

  const pinnedNames = (lots.data?.items ?? []).filter((l) => plan.pinned_lot_ids.includes(l.id)).map((l) => l.ingredient_name_vi);

  const kcalPanel = (
    <BroadsheetLedgerFrame title="Dự toán năng lượng bữa ăn" accentTone="border" innerStyle={{ padding: space.md, gap: space.sm }}>
      <KcalBar low={plan.kcal_low} high={plan.kcal_high} target={plan.e_target_kcal} />
      <T tabular>
        {plan.rice_bowls_per_person
          ? `Gợi ý ${fmtBowls(plan.rice_bowls_per_person)} bát cơm mỗi người.`
          : 'Chưa có mục tiêu năng lượng nên chưa gợi ý số bát cơm.'}
      </T>
    </BroadsheetLedgerFrame>
  );

  const actionGroup = (
    <>
      {overTime ? (
        <Notice tone="warn">
          <T tabular>
            Lịch cần {Math.round(overTime.makespan)} phút, quá {overTime.over} phút so với thời gian đã chọn. Vẫn nấu?
          </T>
          <Button label="Vẫn nấu" onPress={() => cook.mutate(true)} loading={cook.isPending} />
          <Button label="Đổi món khác" kind="ghost" onPress={() => setOverTime(null)} />
        </Notice>
      ) : cook.error && !isCode(cook.error, 'cook_session_in_progress') ? (
        <ErrorBox message={errorText(cook.error)} />
      ) : null}
      <Button
        label={plan.status === 'proposed' ? 'Nhận mâm và nấu' : 'Nấu cả mâm'}
        testID="start-cooking"
        onPress={() => cook.mutate(false)}
        loading={cook.isPending}
      />
      <Button label="Ghép mâm khác" kind="secondary" onPress={onNew} testID="new-plan" />
    </>
  );

  const traySummaryCol = (
    <View style={{ gap: space.lg }}>
      {kcalPanel}
      {actionGroup}
    </View>
  );

  const slotColumn = (
    <View style={{ gap: space.lg }}>
      <Card variant="ledger" style={{ padding: 0, gap: 0, overflow: 'hidden' }}>
        <Row
          style={{
            justifyContent: 'space-between',
            alignItems: 'center',
            paddingHorizontal: space.lg,
            paddingVertical: space.md,
            backgroundColor: c.surfaceAlt,
            borderBottomWidth: 1,
            borderBottomColor: c.hairline,
          }}>
          <T v="label" style={{ color: c.herb, fontFamily: font.displaySemibold }}>Mâm cơm {ordered.length} món</T>
          <T v="small" tone="muted" tabular>
            {plan.rice_bowls_per_person ? `Cơm ${fmtBowls(plan.rice_bowls_per_person)} bát / người` : 'Cơm trắng ăn kèm'}
          </T>
        </Row>
        {ordered.map((i) => {
          const dishPhoto = recipePhotoFor(i.recipe_name_vi, i.slot);
          return (
            <View
              key={i.id}
              style={{
                gap: space.md,
                padding: space.lg,
                borderTopWidth: 1,
                borderTopColor: c.hairline,
              }}>
              <Pressable
                testID={`tray-dish-${i.slot}`}
                accessibilityRole="button"
                accessibilityLabel={`${SLOT_LABEL[i.slot]}: ${i.recipe_name_vi}`}
                onPress={() => {
                  setDish(i);
                  setMode('menu');
                }}
                style={({ pressed }) => ({ opacity: pressed ? 0.78 : 1 })}>
                <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }} gap={space.md}>
                  <Row gap={space.md} style={{ flex: 1, minWidth: 0, flexWrap: 'nowrap' }}>
                    {dishPhoto ? (
                      <Image
                        source={dishPhoto}
                        contentFit="cover"
                        style={{ width: 56, height: 56, borderRadius: radius.sm, backgroundColor: c.surfaceAlt }}
                        accessibilityLabel={i.recipe_name_vi}
                      />
                    ) : (
                      <View
                        style={{
                          width: 56,
                          height: 56,
                          borderRadius: radius.sm,
                          backgroundColor: c.accentSoft,
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}>
                        <T v="label" tone="accent">
                          {SLOT_LABEL[i.slot]}
                        </T>
                      </View>
                    )}
                    <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
                      <T v="small" tone="herb" style={{ fontFamily: font.semibold }}>
                        Món {SLOT_LABEL[i.slot].toLowerCase()}
                      </T>
                      <T v="title" style={{ fontFamily: font.displaySemibold }} numberOfLines={2}>
                        {i.recipe_name_vi}
                      </T>
                      {i.substitutions.length ? <T v="small" tone="muted">Có nguyên liệu thay thế</T> : null}
                    </View>
                  </Row>
                  {i.kcal_per_person != null ? (
                    <View style={{ backgroundColor: c.surfaceAlt, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.sm }}>
                      <T v="small" tone="text" tabular>
                        {Math.round(i.kcal_per_person)} kcal
                      </T>
                    </View>
                  ) : null}
                </Row>
              </Pressable>
              <Row gap={space.xs}>
                <Button
                  label="Xem công thức"
                  kind="ghost"
                  compact
                  onPress={() => router.push({ pathname: '/mon/[id]', params: { id: i.recipe_id, plan: plan.id, item: i.id } })}
                  style={{ paddingHorizontal: space.sm }}
                />
                {plan.status === 'proposed' || plan.status === 'accepted' ? (
                  <>
                    <Button
                      label="Đổi món"
                      kind="secondary"
                      compact
                      onPress={() => {
                        setDish(i);
                        setMode('swap');
                      }}
                      style={{ paddingHorizontal: space.sm }}
                    />
                    <Button
                      label="Thiếu gì?"
                      kind="secondary"
                      compact
                      onPress={() => {
                        setDish(i);
                        setMode('missing');
                      }}
                      style={{ paddingHorizontal: space.sm }}
                    />
                  </>
                ) : null}
              </Row>
            </View>
          );
        })}
      </Card>

      <Row gap={space.sm}>
        {plan.reason_vi ? (
          <View
            testID="plan-reason"
            style={{ backgroundColor: c.okSoft, borderRadius: radius.md, paddingHorizontal: space.md, paddingVertical: space.sm, maxWidth: '100%', flexShrink: 1 }}>
            <T v="small" tone="herb" style={{ flexShrink: 1 }}>{plan.reason_vi}</T>
          </View>
        ) : null}
        {plan.ranker_version_id != null ? (
          <View
            style={{
              backgroundColor: c.infoSoft,
              borderRadius: radius.md,
              paddingHorizontal: space.md,
              paddingVertical: space.sm,
              maxWidth: '100%',
              flexShrink: 1,
            }}>
            <Row gap={space.xs} style={{ flexWrap: 'nowrap', maxWidth: '100%' }}>
              <Icon name="sliders" size={16} color={c.info} />
              <T v="small" tone="info" style={{ fontWeight: '600', flexShrink: 1 }}>
                Ưu tiên theo khẩu vị gia đình
              </T>
            </Row>
          </View>
        ) : null}
      </Row>

      <View style={{ borderTopWidth: 1, borderTopColor: c.hairline, paddingTop: space.md, gap: space.sm }}>
        <Stepper label="Số người ăn" value={persons} onChange={setPersons} min={1} max={6} testID="plan-persons" />
        {persons !== plan.persons ? (
          <Button
            label={`Ghép lại cho ${persons} người`}
            kind="secondary"
            testID="plan-regroup"
            loading={regroup.isPending}
            onPress={() =>
              regroup.mutate({
                meal: plan.meal,
                persons,
                max_minutes: plan.max_minutes,
                coeater_allergen_codes: plan.coeater_allergen_codes,
                pinned_lot_ids: plan.pinned_lot_ids,
              })
            }
          />
        ) : null}
        {regroup.error ? <ErrorBox message={errorText(regroup.error)} /> : null}
      </View>

      {pinnedNames.length ? <T tone="muted">Đồ đã ghim: {pinnedNames.join(', ')}</T> : null}
      {swappedOut.length ? <T v="small" tone="muted">Đã đổi ra: {swappedOut.map((i) => i.recipe_name_vi).join(', ')}</T> : null}

      <Section title="Giờ dọn mâm">
        <Segmented options={[[0, 'Sớm nhất'], [30, 'Sau 30 phút'], [60, 'Sau 1 giờ']]} value={serveIn} onChange={setServeIn} />
      </Section>
    </View>
  );

  return (
    <View style={{ gap: space.lg }} testID="plan-view">
      <View style={{ gap: 2 }}>
        <T v="huge" accessibilityRole="header">
          {MEAL_LABEL[plan.meal]} cho {plan.persons} người
        </T>
        <T tone="muted">
          {plan.status === 'accepted' ? 'Đã chốt mâm, sẵn sàng chia việc nấu từng bếp.' : 'Chạm một món để xem công thức, đổi món hoặc xem đồ thiếu.'}
        </T>
      </View>

      {isDesktop ? (
        <View style={{ flexDirection: 'row', gap: space.xl, alignItems: 'flex-start' }}>
          <View style={{ flex: 5, minWidth: 0 }}>{traySummaryCol}</View>
          <View style={{ flex: 7, minWidth: 0 }}>{slotColumn}</View>
        </View>
      ) : (
        <>
          {slotColumn}
          {kcalPanel}
          {actionGroup}
        </>
      )}

      <Sheet
        visible={!!dish}
        onClose={() => setDish(null)}
        title={dish ? `${SLOT_LABEL[dish.slot]}: ${dish.recipe_name_vi}` : ''}
        testID="sheet-dish">
        {dish && mode === 'menu' ? (
          <>
            {dish.kcal_per_person != null ? (
              <T tone="muted" tabular>
                Khoảng {Math.round(dish.kcal_per_person)} kcal mỗi người.
              </T>
            ) : null}
            <Button
              label="Xem công thức"
              kind="secondary"
              onPress={() => {
                const d = dish;
                setDish(null);
                router.push({ pathname: '/mon/[id]', params: { id: d.recipe_id, plan: plan.id, item: d.id } });
              }}
            />
            {plan.status === 'proposed' || plan.status === 'accepted' ? (
              <>
                <Button label="Đổi món" testID="dish-swap" onPress={() => setMode('swap')} />
                <Button label="Thiếu gì?" kind="secondary" testID="dish-missing" onPress={() => setMode('missing')} />
              </>
            ) : null}
          </>
        ) : null}
        {dish && mode === 'swap' ? (
          <>
            <T>Vì sao muốn đổi món này?</T>
            {SWAP_REASONS.map((r) => (
              <Button
                key={r.v}
                kind="secondary"
                label={r.l}
                testID={`swap-${r.v}`}
                onPress={() => swap.mutate(r.v)}
                disabled={swap.isPending}
              />
            ))}
            {swap.isPending ? <Loading label="Đang tìm món khác…" /> : null}
            {isCode(swap.error, 'no_alternative') ? (
              <Notice tone="warn">
                <T>{errorText(swap.error)} Xem &quot;Thiếu gì?&quot; để thay nguyên liệu, hoặc thêm đồ cần mua vào danh sách đi chợ.</T>
                <Button label="Thiếu gì?" kind="secondary" onPress={() => setMode('missing')} />
              </Notice>
            ) : swap.error ? (
              <ErrorBox message={errorText(swap.error)} />
            ) : null}
          </>
        ) : null}
        {dish && mode === 'missing' ? <Missing plan={plan} item={dish} onChanged={(p) => refresh(p)} /> : null}
      </Sheet>
    </View>
  );
}

// ---- "Thiếu gì?" (UC17) -------------------------------------------------------------------------

function Missing({ plan, item, onChanged }: { plan: Plan; item: Item; onChanged: (p?: Plan) => void }) {
  const { c } = useTheme();
  const q = useQuery({
    queryKey: ['substitutes', plan.id, item.id],
    queryFn: () => call(api.GET('/meal-plans/{id}/items/{itemId}/substitutes', { params: { path: { id: plan.id, itemId: item.id } } })),
  });
  const apply = useMutation({
    mutationFn: (b: Schemas['SubstitutionCreate']) =>
      call(api.POST('/meal-plans/{id}/items/{itemId}/substitutions', { params: { path: { id: plan.id, itemId: item.id } }, body: b })),
    onSuccess: () => {
      q.refetch();
      onChanged();
    },
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} />;
  const items = q.data?.items ?? [];
  if (!items.length) return <Notice tone="ok"><T>Kho đủ nguyên liệu cho món này.</T></Notice>;
  return (
    <View style={{ gap: space.md }} testID="missing-list">
      {items.map((m) => (
        <View
          key={m.original_ingredient_id}
          style={{ borderRadius: radius.md, backgroundColor: c.surfaceAlt, padding: space.md, gap: space.sm }}>
          <ShoppingRow ingredientId={m.original_ingredient_id} name={m.name_vi} needG={m.need_g} haveG={m.available_g_min} itemId={item.id} />
          {m.candidates.length ? (
            <View style={{ gap: space.sm }}>
              <T v="label">Có thể thay bằng</T>
              {m.candidates.map((cand) => (
                <View
                  key={cand.substitute_ingredient_id}
                  style={{ gap: space.xs, borderTopWidth: 1, borderTopColor: c.hairline, paddingTop: space.sm }}>
                  <Row gap={space.xs}>
                    {cand.origin === 'embedding' ? (
                      <View
                        testID="sub-origin-embedding"
                        style={{ backgroundColor: c.infoSoft, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 2, maxWidth: '100%', flexShrink: 1 }}>
                        <Row gap={space.xs} style={{ flexWrap: 'nowrap', maxWidth: '100%' }}>
                          <Icon name="compass" size={14} color={c.info} />
                          <T v="small" tone="info" style={{ fontWeight: '600', flexShrink: 1 }}>
                            Gợi ý cùng nhóm chất
                          </T>
                        </Row>
                      </View>
                    ) : (
                      <View
                        testID="sub-origin-lookup"
                        style={{ backgroundColor: c.herbSoft, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 2, maxWidth: '100%', flexShrink: 1 }}>
                        <T v="small" tone="herb" style={{ fontWeight: '600', flexShrink: 1 }}>
                          Gợi ý chuẩn
                        </T>
                      </View>
                    )}
                  </Row>
                  <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                    <View style={{ flexShrink: 1 }}>
                      <T tabular>
                        {cand.name_vi}, {Math.round(cand.grams)} g (tỷ lệ {Math.round(cand.ratio * 100) / 100})
                      </T>
                      <T v="small" tone="muted" tabular>
                        {cand.in_pantry ? `Kho có ${Math.round(cand.available_g_min ?? 0)} g` : 'Kho chưa có'}
                      </T>
                    </View>
                    <Button
                      label="Dùng thay"
                      kind="secondary"
                      loading={apply.isPending}
                      onPress={() =>
                        apply.mutate({
                          original_ingredient_id: m.original_ingredient_id,
                          substitute_ingredient_id: cand.substitute_ingredient_id,
                          origin: cand.origin,
                        })
                      }
                    />
                  </Row>
                  {!cand.in_pantry ? (
                    <ShoppingRow
                      ingredientId={cand.substitute_ingredient_id}
                      name={cand.name_vi}
                      needG={cand.grams}
                      haveG={cand.available_g_min ?? 0}
                      itemId={item.id}
                    />
                  ) : null}
                </View>
              ))}
            </View>
          ) : (
            <T v="small" tone="muted">
              Chưa có gợi ý thay thế cho nguyên liệu này.
            </T>
          )}
        </View>
      ))}
      {apply.error ? <ErrorBox message={errorText(apply.error)} /> : null}
    </View>
  );
}
