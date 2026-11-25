import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { useLocalSearchParams, useNavigation } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Linking, Pressable, View } from 'react-native';

import { api, call } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { recipePhotoFor } from '@/components/Brand';
import { Icon, SLOT_LABEL } from '@/components/domain';
import { MacroPieLedger } from '@/components/MacroPieLedger';
import { Button, Card, ErrorBox, Loading, Notice, Row, Screen, Section, Stepper, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { addQuickMealLog, defaultMealSlot, MEAL_SLOT_LABEL, type QuickMealLogEntry, removeQuickMealLog } from '@/lib/mealLog';
import { goTab } from '@/lib/nav';
import { enqueueEvents } from '@/lib/outbox';
import { qk, useHasConsent, useLots, useReference } from '@/lib/queries';
import { radius, space, TOUCH, useLayout, useTheme } from '@/theme';

/** Chi tiết món ăn: chỉnh số người ăn, thêm đồ thiếu vào đi chợ 1 chạm, và ghi bữa vào Nhật ký. */
export default function RecipeDetail() {
  const { id, plan, item } = useLocalSearchParams<{ id: string; plan?: string; item?: string }>();
  const { c } = useTheme();
  const { isDesktop } = useLayout();
  const { user } = useSession();
  const qc = useQueryClient();
  const nav = useNavigation();
  const personalization = useHasConsent('personalization');
  const catalog = useCatalog();
  const ref = useReference();
  const lots = useLots();
  const [offlineFallback, setOfflineFallback] = useState(false);
  const [servingsCount, setServingsCount] = useState<number | null>(null);
  const [shopAddedIds, setShopAddedIds] = useState<Record<string, boolean>>({});
  const [batchShopDone, setBatchShopDone] = useState(false);
  const [loggedEntry, setLoggedEntry] = useState<QuickMealLogEntry | null>(null);
  const [logBusy, setLogBusy] = useState(false);

  const q = useQuery({
    queryKey: qk.recipe(id),
    queryFn: async () => {
      try {
        const res = await call(api.GET('/recipes/{id}', { params: { path: { id } } }));
        setOfflineFallback(false);
        return res;
      } catch (e) {
        const cached = catalog.recipes.get(id);
        if (cached) {
          setOfflineFallback(true);
          return cached;
        }
        throw e;
      }
    },
  });

  const sentIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (q.data) nav.setOptions({ title: q.data.name_vi });
    if (q.data && personalization && sentIdRef.current !== id) {
      sentIdRef.current = id;
      void enqueueEvents([{ type: 'viewed', recipe_id: id, meal_plan_id: plan ?? null, meal_plan_item_id: item ?? null }]);
    }
  }, [q.data, personalization, id, plan, item, nav]);

  const pantryTotals = useMemo(() => {
    const m = new Map<string, number>();
    (lots.data?.items ?? []).forEach((l) => {
      if (l.available) m.set(l.ingredient_id, (m.get(l.ingredient_id) ?? 0) + l.balance_g_min);
    });
    return m;
  }, [lots.data]);

  const addShopItem = useMutation({
    mutationFn: ({ ingredient_id, qty_g }: { ingredient_id: string; qty_g: number }) =>
      call(api.POST('/shopping-items', { body: { ingredient_id, qty_g: Math.max(1, Math.round(qty_g)) } })),
    onSuccess: (_res, vars) => {
      setShopAddedIds((prev) => ({ ...prev, [vars.ingredient_id]: true }));
      qc.invalidateQueries({ queryKey: qk.shopping });
    },
  });

  const addAllMissing = useMutation({
    mutationFn: async (items: { ingredient_id: string; qty_g: number }[]) => {
      await Promise.all(
        items.map((x) =>
          call(api.POST('/shopping-items', { body: { ingredient_id: x.ingredient_id, qty_g: Math.max(1, Math.round(x.qty_g)) } })),
        ),
      );
      return items;
    },
    onSuccess: (items) => {
      const next: Record<string, boolean> = {};
      items.forEach((x) => {
        next[x.ingredient_id] = true;
      });
      setShopAddedIds((prev) => ({ ...prev, ...next }));
      setBatchShopDone(true);
      qc.invalidateQueries({ queryKey: qk.shopping });
    },
  });

  if (q.isLoading) return <Screen><Loading /></Screen>;
  if (q.error || !q.data) return <Screen><ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} /></Screen>;
  const r = q.data;
  const activeServings = servingsCount ?? r.servings;
  const scale = activeServings / Math.max(1, r.servings);

  const macroNum = (direct: number | null | undefined, code: string) =>
    direct ?? r.nutrition.find((n) => n.nutrient_code === code)?.per_serving ?? null;

  const proteinG = macroNum(r.protein_g, 'protein_g') ?? 0;
  const carbsG = macroNum(r.carbs_g, 'glucid_g') ?? 0;
  const fatG = macroNum(r.fat_g, 'lipid_g') ?? 0;
  const fiberG = macroNum(r.fiber_g, 'fiber_g') ?? 0;
  const sodiumMg = r.nutrition.find((n) => n.nutrient_code === 'sodium_mg')?.per_serving ?? null;
  const sugarG = r.nutrition.find((n) => n.nutrient_code === 'sugar_g')?.per_serving ?? null;
  const hasMacroData =
    r.protein_g != null ||
    r.carbs_g != null ||
    r.fat_g != null ||
    r.fiber_g != null ||
    r.nutrition.some((n) => ['protein_g', 'glucid_g', 'lipid_g', 'fiber_g'].includes(n.nutrient_code));
  const totalIngGrams = r.ingredients.filter((i) => !i.is_optional).reduce((acc, i) => acc + i.grams, 0);
  const servingMassG = totalIngGrams > 0 ? Math.round(totalIngGrams / Math.max(1, r.servings)) : null;

  const extraNutrients = r.nutrition.filter(
    (n) => !['energy_kcal', 'protein_g', 'glucid_g', 'lipid_g', 'fiber_g'].includes(n.nutrient_code),
  );

  const missingToShop = r.ingredients
    .filter((i) => !i.is_staple && !i.is_optional)
    .map((i) => {
      const scaledG = Math.round(i.grams * scale);
      const have = pantryTotals.get(i.ingredient_id) ?? 0;
      return { ingredient_id: i.ingredient_id, qty_g: Math.max(0, scaledG - have) };
    })
    .filter((x) => x.qty_g > 0 && !shopAddedIds[x.ingredient_id]);

  const logDishNow = async () => {
    if (logBusy) return;
    setLogBusy(true);
    try {
      const slot = defaultMealSlot();
      const entry = await addQuickMealLog(
        {
          meal_slot: slot,
          title_vi: r.name_vi,
          source_kind: 'recipe',
          source_ref_id: r.id,
          portion_label: '1 khẩu phần',
          modifiers_vi: [],
          kcal: Math.round(r.kcal_per_serving ?? 280),
          kcal_low: Math.round((r.kcal_per_serving ?? 280) * 0.85),
          kcal_high: Math.round((r.kcal_per_serving ?? 280) * 1.15),
          protein_g: proteinG,
          carbs_g: carbsG,
          fat_g: fatG,
          fiber_g: fiberG,
          provenance_label_vi: 'Công thức cơm nhà Mỹ Vị',
        },
        user?.id,
      );
      setLoggedEntry(entry);
      await Promise.all([qc.invalidateQueries({ queryKey: ['quick-logs'] }), qc.invalidateQueries({ queryKey: ['journal'] })]);
    } finally {
      setLogBusy(false);
    }
  };

  const validSources = r.sources
    .map((s) => {
      if (!/^https?:\/\//i.test(s.url)) return null;
      try {
        const parsed = new URL(s.url);
        if ((parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.hostname.length > 0) {
          return { title: s.title, safeUrl: s.url, host: parsed.hostname.replace(/^www\./, '') };
        }
      } catch {
        return null;
      }
      return null;
    })
    .filter((s): s is { title: string; safeUrl: string; host: string } => s !== null);

  const leftCol = (
    <View style={{ gap: space.lg }}>
      {r.make_ahead ? (
        <View style={{ borderRadius: radius.md, borderWidth: 1, borderColor: c.hairline, backgroundColor: c.surfaceAlt, padding: space.lg }}>
          <T>
            Cần chuẩn bị trước {r.make_ahead.item_name_vi} ({r.make_ahead.whole_dish ? 'cả món' : `bước 1 đến ${r.make_ahead.through_step_no}`}).
          </T>
        </View>
      ) : null}

      <Section title="Nguyên liệu">
        <Card style={{ gap: space.md }}>
          <Stepper
            label="Số người ăn"
            value={activeServings}
            onChange={(next) => {
              setServingsCount(next);
              setBatchShopDone(false);
            }}
            min={1}
            max={8}
            testID="recipe-servings"
          />
          {r.ingredients.map((i) => {
            const scaledGrams = Math.round(i.grams * scale);
            const have = pantryTotals.get(i.ingredient_id) ?? 0;
            const short = Math.max(0, Math.round(scaledGrams - have));
            const enough = short <= 0;
            const addedShop = Boolean(shopAddedIds[i.ingredient_id]);
            return (
              <Row key={i.ingredient_id} style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }} gap={space.sm}>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <T>
                    {i.name_vi}
                    {i.is_optional ? ' (tuỳ chọn)' : ''}
                  </T>
                </View>
                <Row gap={space.xs} style={{ flexWrap: 'nowrap' }}>
                  {lots.data ? (
                    <View
                      style={{
                        backgroundColor: i.is_staple ? c.surfaceAlt : enough ? c.herbSoft : c.warnSoft,
                        borderRadius: radius.sm,
                        paddingHorizontal: space.sm,
                        paddingVertical: 2,
                      }}>
                      <T v="small" tone={i.is_staple ? 'text' : enough ? 'herb' : 'warn'} tabular>
                        {i.is_staple ? 'Gia vị sẵn' : enough ? 'Có đủ' : `Thiếu ${short} g`}
                      </T>
                    </View>
                  ) : null}
                  {!i.is_staple && short > 0 ? (
                    addedShop ? (
                      <T v="small" tone="herb">Đã thêm</T>
                    ) : (
                      <Button
                        label="+ Đi chợ"
                        kind="ghost"
                        compact
                        testID={`recipe-shop-${i.ingredient_id}`}
                        onPress={() => addShopItem.mutate({ ingredient_id: i.ingredient_id, qty_g: short })}
                        style={{ paddingHorizontal: space.xs }}
                      />
                    )
                  ) : null}
                  <T v="label" tabular>
                    {scaledGrams} g
                  </T>
                </Row>
              </Row>
            );
          })}
          {missingToShop.length > 0 ? (
            <Button
              label={`Thêm ${missingToShop.length} đồ thiếu vào Đi chợ`}
              kind="secondary"
              compact
              testID="recipe-shop-all"
              loading={addAllMissing.isPending}
              onPress={() => addAllMissing.mutate(missingToShop)}
            />
          ) : batchShopDone ? (
            <T v="small" tone="herb">Đã thêm toàn bộ nguyên liệu còn thiếu vào danh sách Đi chợ.</T>
          ) : null}
        </Card>
      </Section>

      {hasMacroData ? (
        <Section title="Phân tích dinh dưỡng mỗi người">
          <View style={{ gap: space.sm }}>
            <MacroPieLedger
              title="Dinh dưỡng 1 khẩu phần"
              proteinG={proteinG}
              carbsG={carbsG}
              fatG={fatG}
              fiberG={fiberG}
              totalKcal={r.kcal_per_serving}
              massG={servingMassG}
              sodiumMg={sodiumMg}
              sugarG={sugarG}
              context="meal"
            />
            {extraNutrients.length ? (
              <Card style={{ gap: space.xs }}>
                {extraNutrients.map((n) => {
                  const meta = ref.data?.nutrients.find((x) => x.code === n.nutrient_code);
                  return (
                    <Row key={n.nutrient_code} style={{ justifyContent: 'space-between' }}>
                      <T v="small" tone="muted">
                        {meta?.name_vi ?? n.nutrient_code}
                      </T>
                      <T v="small" tabular>
                        {Math.round(n.per_serving * 10) / 10} {meta?.unit ?? ''}
                      </T>
                    </Row>
                  );
                })}
              </Card>
            ) : null}
            <T v="small" tone="muted">
              Tính từ bảng thành phần thực phẩm.
            </T>
          </View>
        </Section>
      ) : null}
    </View>
  );

  const rightCol = (
    <View style={{ gap: space.lg }}>
      <Section title="Các bước thực hiện">
        <View style={{ borderRadius: radius.md, borderWidth: 1, borderColor: c.hairline, backgroundColor: c.surface, padding: space.lg, gap: space.md }}>
          {r.steps.map((s) => (
            <View key={s.step_no} style={{ flexDirection: 'row', gap: space.md }}>
              <T v="title" tabular style={{ width: 28, color: s.kind === 'active' ? c.accent : c.herb }}>
                {s.step_no}.
              </T>
              <View style={{ flex: 1, gap: 2 }}>
                <T>{s.text_vi}</T>
                <T v="small" tone="muted" tabular>
                  {s.minutes} phút, {s.kind === 'active' ? 'đứng bếp' : 'chờ'}
                  {s.uses_burner ? ', dùng bếp' : ''}
                </T>
              </View>
            </View>
          ))}
        </View>
      </Section>

      {validSources.length ? (
        <Section title="Nguồn công thức">
          <View style={{ borderRadius: radius.md, borderWidth: 1, borderColor: c.hairline, backgroundColor: c.surface, overflow: 'hidden' }}>
            {validSources.map((s, i) => (
              <Pressable
                key={s.safeUrl}
                accessibilityRole="link"
                accessibilityLabel={`Mở nguồn tham khảo ${s.title}`}
                onPress={() => void Linking.openURL(s.safeUrl).catch(() => {})}
                style={({ pressed }) => ({
                  minHeight: TOUCH,
                  paddingHorizontal: space.lg,
                  paddingVertical: space.md,
                  borderTopWidth: i > 0 ? 1 : 0,
                  borderTopColor: c.hairline,
                  backgroundColor: pressed ? c.surfaceAlt : 'transparent',
                  flexDirection: 'row',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: space.sm,
                })}>
                <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
                  <T v="label" numberOfLines={2}>
                    {s.title}
                  </T>
                  <T v="small" tone="muted" numberOfLines={1}>
                    {s.host}
                  </T>
                </View>
                <Icon name="arrow-up-right" size={18} color={c.accent} />
              </Pressable>
            ))}
          </View>
        </Section>
      ) : null}
    </View>
  );

  const methodName = ref.data?.cooking_methods.find((m) => m.code === r.method_code)?.name_vi ?? r.method_code;
  const heroPhoto = recipePhotoFor(r.name_vi, r.slot);

  return (
    <Screen
      testID="screen-recipe"
      footer={
        loggedEntry ? (
          <Notice tone="ok" testID="recipe-logged-notice">
            <T v="label">
              Đã ghi {loggedEntry.title_vi} ({loggedEntry.kcal} kcal, bữa {MEAL_SLOT_LABEL[loggedEntry.meal_slot]}) vào Nhật ký.
            </T>
            <Row gap={space.xs}>
              <Button label="Xem Nhật ký" kind="secondary" compact onPress={() => goTab('/nhat-ky')} />
              <Button
                label="Hoàn tác"
                kind="ghost"
                compact
                onPress={async () => {
                  await removeQuickMealLog(loggedEntry.id, user?.id);
                  setLoggedEntry(null);
                  await Promise.all([qc.invalidateQueries({ queryKey: ['quick-logs'] }), qc.invalidateQueries({ queryKey: ['journal'] })]);
                }}
              />
            </Row>
          </Notice>
        ) : (
          <Button
            label={`Tôi vừa nấu / ăn món này${r.kcal_per_serving ? ` (${Math.round(r.kcal_per_serving)} kcal)` : ''}`}
            testID="recipe-log-meal"
            loading={logBusy}
            onPress={() => void logDishNow()}
          />
        )
      }>
      {offlineFallback ? (
        <Notice tone="info">
          <T>Đang xem ngoại tuyến (chưa có mạng).</T>
        </Notice>
      ) : null}
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        {heroPhoto ? (
          <Image
            source={heroPhoto}
            contentFit="cover"
            style={{ width: '100%', height: isDesktop ? 260 : 196, backgroundColor: c.surfaceAlt }}
            accessibilityLabel={`Ảnh món ${r.name_vi}`}
          />
        ) : null}
        <View style={{ padding: space.xl, gap: space.xs }}>
          <Row gap={space.xs}>
            <View style={{ backgroundColor: c.accentSoft, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 2, maxWidth: '100%', flexShrink: 1 }}>
              <T v="small" tone="accent" style={{ fontWeight: '600', flexShrink: 1 }}>
                {SLOT_LABEL[r.slot]}
              </T>
            </View>
            <View style={{ backgroundColor: c.surfaceAlt, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 2, maxWidth: '100%', flexShrink: 1 }}>
              <T v="small" style={{ flexShrink: 1 }}>{methodName}</T>
            </View>
          </Row>
          <T v="huge" accessibilityRole="header">
            {r.name_vi}
          </T>
          <T tone="muted" tabular>
            Gốc {r.servings} người · Đang chỉnh {activeServings} người · ~{r.total_minutes} phút{r.kcal_per_serving ? ` · ${Math.round(r.kcal_per_serving)} kcal/người` : ''}
          </T>
        </View>
      </Card>

      {isDesktop ? (
        <View style={{ flexDirection: 'row', gap: space.xl, alignItems: 'flex-start' }}>
          <View style={{ flex: 5, minWidth: 0 }}>{leftCol}</View>
          <View style={{ flex: 7, minWidth: 0 }}>{rightCol}</View>
        </View>
      ) : (
        <>
          {leftCol}
          {rightCol}
        </>
      )}
    </Screen>
  );
}
