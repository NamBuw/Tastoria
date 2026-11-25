import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Pressable, useWindowDimensions, View } from 'react-native';

import { api, call, isCode, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { Icon } from '@/components/domain';
import { AddLotSheet, IngredientSearch } from '@/components/pantryForms';
import { Button, Card, Checkbox, Chip, Empty, ErrorBox, Field, Loading, Notice, Row, Screen, Section, Sheet, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { fetchAllPages, qk, useReference } from '@/lib/queries';
import { radius, space, TOUCH, useTheme } from '@/theme';

type ShoppingItem = Schemas['ShoppingItem'];
const MERGE = { headers: { 'Content-Type': 'application/merge-patch+json' } };

function quantityToGrams(
  qty: Schemas['QuantityInput'],
  ing: Schemas['Ingredient'],
  ref?: Schemas['ReferenceData'],
): number {
  if ('g_min' in qty) return Math.max(1, Math.round(qty.g_min));
  if ('count' in qty) {
    const unit = ing.units.find((u) => u.unit_code === qty.unit_code);
    return Math.max(1, Math.round(qty.count * (unit?.grams_per_unit ?? 50)));
  }
  const lv = ref?.qty_levels.find((l) => l.food_group_code === ing.food_group_code && l.level === qty.qty_level);
  if (lv) return Math.max(1, Math.round((lv.g_min + lv.g_max) / 2));
  return qty.qty_level === 'it' ? 100 : qty.qty_level === 'nhieu' ? 400 : 200;
}

/** Shared body for Đi chợ (usable standalone at /di-cho and inline inside Tủ lạnh). */
export function ShoppingListBody({ showPageTitle = true }: { showPageTitle?: boolean }) {
  const { c } = useTheme();
  const { width } = useWindowDimensions();
  const desktop = width >= 1024;
  const qc = useQueryClient();
  const { status } = useSession();
  const catalog = useCatalog();
  const ref = useReference();

  const list = useQuery({
    queryKey: qk.shopping,
    enabled: status === 'signedIn',
    queryFn: () =>
      fetchAllPages((cursor) =>
        call(api.GET('/shopping-items', { params: { query: { status: ['open', 'bought'], cursor, limit: 100 } } })),
      ),
  });

  const [adding, setAdding] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const [fallback, setFallback] = useState<{ item: ShoppingItem; ingredient: Schemas['Ingredient'] } | null>(null);

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas['ShoppingItemPatch'] }) =>
      call(api.PATCH('/shopping-items/{id}', { params: { path: { id } }, body, ...MERGE })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.shopping }),
  });

  const toPantry = useMutation({
    mutationFn: async ({ item, body }: { item: ShoppingItem; body: Schemas['ShoppingItemToPantryRequest'] }) => {
      setBusyId(item.id);
      return call(api.POST('/shopping-items/{id}/to-pantry', { params: { path: { id: item.id } }, body }));
    },
    onSuccess: (_res, vars) => {
      qc.invalidateQueries({ queryKey: qk.shopping });
      qc.invalidateQueries({ queryKey: ['lots'] });
      setToast(`Đã cho ${vars.item.ingredient_name_vi} vào Tủ lạnh`);
    },
    onSettled: () => setBusyId(null),
  });

  const resolveIngredientForItem = async (item: ShoppingItem): Promise<Schemas['Ingredient']> => {
    const cached = catalog.ingredients.get(item.ingredient_id);
    if (cached) return cached;
    try {
      const r = await call(api.GET('/ingredients', { params: { query: { q: item.ingredient_name_vi, limit: 12 } } }));
      const found = r.items.find((x) => x.id === item.ingredient_id) ?? r.items[0];
      if (found) return found;
    } catch {
      // fall through
    }
    return {
      id: item.ingredient_id,
      name_vi: item.ingredient_name_vi,
      food_group_code: 'khac',
      is_staple: false,
      countable: false,
      shelf_life_days: null,
      allergen_codes: [],
      units: [],
      synonyms: [],
    };
  };

  const openFallbackSheet = async (item: ShoppingItem) => {
    toPantry.reset();
    const ing = await resolveIngredientForItem(item);
    setFallback({ item, ingredient: ing });
  };

  const handleToPantryPress = async (item: ShoppingItem) => {
    if (item.qty_g == null) {
      await openFallbackSheet(item);
      return;
    }
    try {
      await toPantry.mutateAsync({ item, body: {} });
    } catch (e) {
      if (isCode(e, 'validation_error') || isCode(e, 'qty_required')) {
        await openFallbackSheet(item);
      }
    }
  };

  const items = list.data?.items ?? [];
  const open = items.filter((i) => i.status === 'open');
  const bought = items.filter((i) => i.status === 'bought');
  const batchable = bought.filter((i) => i.qty_g != null);

  const handleBatch = async () => {
    if (!batchable.length) return;
    setBatchBusy(true);
    try {
      let ok = 0;
      let fail = 0;
      for (const item of batchable) {
        try {
          await call(api.POST('/shopping-items/{id}/to-pantry', { params: { path: { id: item.id } }, body: {} }));
          ok += 1;
        } catch {
          fail += 1;
        }
      }
      qc.invalidateQueries({ queryKey: qk.shopping });
      qc.invalidateQueries({ queryKey: ['lots'] });
      setToast(
        fail > 0
          ? `Đã cho ${ok} món vào Tủ lạnh, ${fail} món chưa chuyển được.`
          : `Đã cho tất cả ${ok} món vào Tủ lạnh.`,
      );
    } finally {
      setBatchBusy(false);
    }
  };

  const openSection = open.length ? (
    <Section title={`Cần mua (${open.length})`}>
      <Card style={{ gap: space.sm }}>
        {open.map((i, idx) => (
          <View
            key={i.id}
            style={{
              borderTopWidth: idx ? 1 : 0,
              borderTopColor: c.hairline,
              paddingTop: idx ? space.sm : 0,
            }}>
            <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }} gap={space.sm}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Checkbox
                  testID={`shop-item-${i.ingredient_name_vi}`}
                  checked={false}
                  onChange={() => patch.mutate({ id: i.id, body: { status: 'bought' } })}
                  label={i.ingredient_name_vi}
                  sub={
                    <T v="small" tone="muted" tabular>
                      {[i.qty_g ? `khoảng ${Math.round(i.qty_g)} g` : null, i.note, i.source_meal_plan_item_id ? 'cho mâm hôm nay' : null]
                        .filter(Boolean)
                        .join(', ') || 'chưa ghi lượng'}
                    </T>
                  }
                />
              </View>
              <Row gap={space.xs} style={{ flexWrap: 'nowrap' }}>
                <Button
                  label="Cất vào tủ"
                  kind="secondary"
                  testID={`shop-to-pantry-${i.ingredient_name_vi}`}
                  loading={busyId === i.id && toPantry.isPending}
                  onPress={() => void handleToPantryPress(i)}
                  style={{ paddingHorizontal: space.md, minHeight: 40 }}
                />
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Bỏ ${i.ingredient_name_vi} khỏi danh sách`}
                  onPress={() => patch.mutate({ id: i.id, body: { status: 'dropped' } })}
                  style={({ pressed }) => ({
                    minWidth: TOUCH,
                    minHeight: TOUCH,
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRadius: radius.md,
                    backgroundColor: pressed ? c.surfaceAlt : 'transparent',
                  })}>
                  <Icon name="trash" size={18} color={c.muted} />
                </Pressable>
              </Row>
            </Row>
          </View>
        ))}
      </Card>
    </Section>
  ) : null;

  const boughtSection = bought.length ? (
    <Section
      title={`Đã mua (${bought.length})`}
      right={
        batchable.length > 1 ? (
          <Button label="Cất tất cả vào tủ" kind="secondary" loading={batchBusy} onPress={() => void handleBatch()} />
        ) : null
      }>
      <T v="small" tone="muted">
        Bấm &quot;Cất vào tủ&quot; để chuyển thẳng thành nguyên liệu mới trong Tủ lạnh.
      </T>
      <Card style={{ gap: space.sm }}>
        {bought.map((i, idx) => (
          <View
            key={i.id}
            style={{
              borderTopWidth: idx ? 1 : 0,
              borderTopColor: c.hairline,
              paddingTop: idx ? space.sm : 0,
              gap: space.xs,
            }}>
            <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Checkbox
                  checked
                  onChange={() => patch.mutate({ id: i.id, body: { status: 'open' } })}
                  label={i.ingredient_name_vi}
                  sub={
                    i.qty_g != null ? (
                      <T v="small" tone="muted" tabular>
                        khoảng {Math.round(i.qty_g)} g
                      </T>
                    ) : undefined
                  }
                />
              </View>
              <Button
                label="Cất vào tủ"
                kind="secondary"
                testID={`shop-to-pantry-${i.ingredient_name_vi}`}
                loading={busyId === i.id && toPantry.isPending}
                onPress={() => void handleToPantryPress(i)}
                style={{ paddingHorizontal: space.md, minHeight: 40 }}
              />
            </Row>
          </View>
        ))}
      </Card>
    </Section>
  ) : null;

  return (
    <View style={{ gap: space.lg }}>
      <Row style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        {showPageTitle ? (
          <T v="huge" accessibilityRole="header">
            Đi chợ
          </T>
        ) : (
          <T v="h2" accessibilityRole="header">
            Danh sách cần mua
          </T>
        )}
        <Button
          label="Thêm đồ cần mua"
          testID="shop-add"
          icon={<Icon name="plus" size={18} color={c.onAccent} />}
          onPress={() => setAdding(true)}
        />
      </Row>

      <View accessibilityLiveRegion="polite">
        {toast ? (
          <Notice tone="ok">
            <T>{toast}</T>
          </Notice>
        ) : null}
      </View>

      {list.isLoading ? <Loading /> : null}
      {list.error ? <ErrorBox message={errorText(list.error)} onRetry={() => list.refetch()} /> : null}
      {patch.error ? <ErrorBox message={errorText(patch.error)} /> : null}
      {toPantry.error && !isCode(toPantry.error, 'validation_error', 'qty_required') ? <ErrorBox message={errorText(toPantry.error)} /> : null}

      {list.data && !items.length ? (
        <Empty
          title="Danh sách đi chợ đang trống"
          body="Thêm nguyên liệu cần mua tại đây, hoặc bấm + Đi chợ trực tiếp trên trang chi tiết món ăn."
          action={<Button label="Thêm đồ cần mua" onPress={() => setAdding(true)} />}
        />
      ) : null}

      {desktop ? (
        <View style={{ flexDirection: 'row', gap: space.xl, alignItems: 'flex-start' }}>
          <View style={{ flex: 7, minWidth: 0 }}>{openSection}</View>
          <View style={{ flex: 5, minWidth: 0 }}>{boughtSection}</View>
        </View>
      ) : (
        <>
          {openSection}
          {boughtSection}
        </>
      )}

      <AddSheet visible={adding} onClose={() => setAdding(false)} />

      {fallback ? (
        <AddLotSheet
          visible
          title={`Cho ${fallback.item.ingredient_name_vi} vào Tủ lạnh`}
          initialIngredient={fallback.ingredient}
          onClose={() => setFallback(null)}
          onCustomSubmit={async (body) => {
            const qty_g = quantityToGrams(body.quantity, fallback.ingredient, ref.data);
            await call(
              api.POST('/shopping-items/{id}/to-pantry', {
                params: { path: { id: fallback.item.id } },
                body: { qty_g: qty_g || 200, acquired_at: body.acquired_at ?? null },
              }),
            );
            qc.invalidateQueries({ queryKey: qk.shopping });
            qc.invalidateQueries({ queryKey: ['lots'] });
            setToast(`Đã cho ${fallback.item.ingredient_name_vi} vào Tủ lạnh`);
            setFallback(null);
          }}
        />
      ) : null}
    </View>
  );
}

/** Danh sách đi chợ (/di-cho). */
export default function Shopping() {
  return (
    <Screen testID="screen-shopping">
      <ShoppingListBody showPageTitle />
    </Screen>
  );
}

function AddSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [ing, setIng] = useState<Schemas['Ingredient'] | null>(null);
  const [grams, setGrams] = useState('');
  const [note, setNote] = useState('');
  const trimmedGrams = grams.trim();
  const parsedGrams = trimmedGrams ? Number(trimmedGrams) : null;
  const invalidGrams = trimmedGrams !== '' && (parsedGrams === null || !Number.isFinite(parsedGrams) || parsedGrams <= 0);
  const add = useMutation({
    mutationFn: () =>
      call(
        api.POST('/shopping-items', {
          body: { ingredient_id: ing!.id, qty_g: parsedGrams && parsedGrams > 0 ? parsedGrams : null, note: note.trim() || null },
        }),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.shopping });
      setIng(null);
      setGrams('');
      setNote('');
      onClose();
    },
  });
  return (
    <Sheet visible={visible} onClose={onClose} title="Thêm đồ cần mua">
      <IngredientSearch onPick={setIng} picked={ing} />
      <Field
        label="Khoảng bao nhiêu gam (không bắt buộc)"
        value={grams}
        onChangeText={(v) => setGrams(v.replace(/[^0-9]/g, ''))}
        keyboardType="number-pad"
        inputMode="numeric"
        error={invalidGrams ? 'Khối lượng phải lớn hơn 0 gam.' : undefined}
      />
      <Row gap={space.xs}>
        {(['100', '250', '500', '1000'] as const).map((preset) => (
          <Chip
            key={preset}
            label={preset === '1000' ? '1 kg' : `${preset} g`}
            selected={grams === preset}
            onPress={() => setGrams(preset)}
          />
        ))}
      </Row>
      <Field label="Ghi chú (không bắt buộc)" value={note} onChangeText={setNote} maxLength={500} placeholder="VD: 1 bó nhỏ, loại ngon…" />
      {add.error ? <ErrorBox message={errorText(add.error)} /> : null}
      <Button label="Thêm" onPress={() => add.mutate()} disabled={!ing || invalidGrams} loading={add.isPending} />
    </Sheet>
  );
}
