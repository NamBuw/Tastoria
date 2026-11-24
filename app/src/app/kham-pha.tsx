import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { memo, useEffect, useMemo, useState } from 'react';
import { FlatList, Pressable, View } from 'react-native';

import { api, ApiError, call, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { recipePhotoFor } from '@/components/Brand';
import { Icon, SLOT_LABEL } from '@/components/domain';
import { Button, Card, Chip, Empty, ErrorBox, Field, Loading, Notice, Row, Screen, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { qk, useLots, useReference } from '@/lib/queries';
import { font, radius, space, TOUCH, useLayout, useTheme } from '@/theme';

type RecipeSummary = Schemas['RecipeSummary'];
type SlotFilter = 'all' | 'man' | 'rau' | 'canh';

function norm(s: string) {
  return s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd');
}

const RecipeCard = memo(function RecipeCard({
  recipe,
  methodName,
  multiCol,
  onPress,
}: {
  recipe: RecipeSummary;
  methodName: string;
  multiCol: boolean;
  onPress: () => void;
}) {
  const { c } = useTheme();
  const ratio = recipe.pantry_match_ratio;
  const fullMatch = ratio != null && ratio >= 1;
  const photo = recipePhotoFor(recipe.name_vi, recipe.slot);
  return (
    <Pressable
      testID="explore-recipe-card"
      accessibilityRole="button"
      accessibilityLabel={`Xem món ${recipe.name_vi}`}
      onPress={onPress}
      style={({ pressed }) => [
        multiCol ? { flex: 1, minWidth: 0 } : undefined,
        { minHeight: TOUCH, opacity: pressed ? 0.92 : 1 },
      ]}>
      <Card style={{ padding: 0, overflow: 'hidden', gap: 0, flex: multiCol ? 1 : undefined, justifyContent: 'space-between' }}>
        {photo ? (
          <Image
            source={photo}
            contentFit="cover"
            style={{ width: '100%', height: 132, backgroundColor: c.surfaceAlt }}
            accessibilityLabel={recipe.name_vi}
          />
        ) : null}
        <View style={{ padding: space.lg, gap: space.xs }}>
          <Row style={{ justifyContent: 'space-between', flexWrap: 'wrap' }} gap={space.xs}>
              <View style={{ backgroundColor: c.accentSoft, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 2 }}>
                <T v="small" tone="accent" style={{ fontWeight: '600' }}>
                  {SLOT_LABEL[recipe.slot]}
                </T>
              </View>
              {ratio != null ? (
                <View
                  style={{
                    backgroundColor: fullMatch ? c.herbSoft : c.warnSoft,
                    borderRadius: radius.sm,
                    paddingHorizontal: space.sm,
                    paddingVertical: 2,
                  }}>
                  <T v="small" tone={fullMatch ? 'herb' : 'warn'} tabular style={{ fontWeight: '600' }}>
                    {fullMatch ? 'Đủ đồ' : `${Math.round(ratio * 100)}% đồ`}
                  </T>
                </View>
              ) : null}
            </Row>
            <T v="title" style={{ marginTop: 2, fontFamily: font.displaySemibold }}>{recipe.name_vi}</T>
            <T v="small" tone="muted" tabular>
              {methodName}, {recipe.total_minutes} phút
              {recipe.kcal_per_serving != null ? `, ${Math.round(recipe.kcal_per_serving)} kcal` : ''}
            </T>
        </View>
        {(recipe.protein_g != null || recipe.carbs_g != null || recipe.fat_g != null || recipe.fiber_g != null) ? (
          <Row
            gap={space.sm}
            style={{
              borderTopWidth: 1,
              borderTopColor: c.hairline,
              paddingHorizontal: space.lg,
              paddingVertical: space.sm,
              backgroundColor: c.surfaceAlt,
            }}>
            {recipe.protein_g != null ? (
              <T v="small" tabular style={{ color: c.macro.protein }}>
                Đạm {Math.round(recipe.protein_g)}g
              </T>
            ) : null}
            {recipe.carbs_g != null ? (
              <T v="small" tabular style={{ color: c.macro.carb }}>
                Tinh bột {Math.round(recipe.carbs_g)}g
              </T>
            ) : null}
            {recipe.fat_g != null ? (
              <T v="small" tabular style={{ color: c.macro.fat }}>
                Béo {Math.round(recipe.fat_g)}g
              </T>
            ) : null}
            {recipe.fiber_g != null ? (
              <T v="small" tabular style={{ color: c.macro.fiber }}>
                Xơ {Math.round(recipe.fiber_g)}g
              </T>
            ) : null}
          </Row>
        ) : null}
      </Card>
    </Pressable>
  );
});

/** Khám phá món Việt (/kham-pha): search, filter, macros, pantry match, offline catalog fallback. */
export default function ExploreRecipes() {
  const { c } = useTheme();
  const { status } = useSession();
  const router = useRouter();
  const { recipeCols: cols } = useLayout();

  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [slot, setSlot] = useState<SlotFilter>('all');
  const [maxMinutes, setMaxMinutes] = useState<number | undefined>(undefined);
  const [methodCode, setMethodCode] = useState<string | undefined>(undefined);
  const [pantryMatch, setPantryMatch] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);

  const ref = useReference();
  const catalog = useCatalog();
  const lots = useLots();

  const filters = useMemo(
    () => ({
      q: debounced || undefined,
      slot: slot === 'all' ? undefined : slot,
      max_minutes: maxMinutes,
      method_code: methodCode,
      pantry_match: pantryMatch || undefined,
    }),
    [debounced, slot, maxMinutes, methodCode, pantryMatch],
  );

  const q = useInfiniteQuery({
    queryKey: qk.recipes(filters),
    enabled: status === 'signedIn',
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/recipes', {
          params: { query: { ...filters, cursor: pageParam, limit: 20 } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const qc = useQueryClient();
  const anyRecipeOffline = qc
    .getQueryCache()
    .findAll({ queryKey: ['recipes'] })
    .some((entry) => entry.state.status === 'error' && entry.state.error instanceof ApiError && entry.state.error.status === 0);
  const isOffline = ((q.isError && q.error instanceof ApiError && q.error.status === 0) || (anyRecipeOffline && !q.data)) && !!catalog.data;

  const methodMap = useMemo(() => {
    const m = new Map<string, string>();
    (ref.data?.cooking_methods ?? []).forEach((cm) => m.set(cm.code, cm.name_vi));
    return m;
  }, [ref.data]);

  const pantryTotals = useMemo(() => {
    const m = new Map<string, number>();
    (lots.data?.items ?? []).forEach((l) => {
      if (l.available) m.set(l.ingredient_id, (m.get(l.ingredient_id) ?? 0) + l.balance_g_min);
    });
    return m;
  }, [lots.data]);

  const items: RecipeSummary[] = useMemo(() => {
    if (!isOffline && q.data) {
      return q.data.pages.flatMap((p) => p.items);
    }
    if (isOffline && catalog.data) {
      const nq = norm(debounced);
      return catalog.data.recipes
        .filter((r) => r.status === 'published')
        .map((r): RecipeSummary => {
          const mains = r.ingredients.filter((i) => i.role === 'main' && !i.is_optional);
          const matched = mains.filter((i) => (pantryTotals.get(i.ingredient_id) ?? 0) >= i.grams).length;
          const ratio = mains.length ? matched / mains.length : 1;
          return { ...r, pantry_match_ratio: ratio };
        })
        .filter((r) => {
          if (slot !== 'all' && r.slot !== slot) return false;
          if (maxMinutes != null && r.total_minutes > maxMinutes) return false;
          if (methodCode && r.method_code !== methodCode) return false;
          if (pantryMatch && (r.pantry_match_ratio ?? 0) < 1) return false;
          if (nq && !norm(r.name_vi).includes(nq)) return false;
          return true;
        });
    }
    return [];
  }, [isOffline, q.data, catalog.data, debounced, slot, maxMinutes, methodCode, pantryMatch, pantryTotals]);

  const clearFilters = () => {
    setSearch('');
    setDebounced('');
    setSlot('all');
    setMaxMinutes(undefined);
    setMethodCode(undefined);
    setPantryMatch(false);
  };

  const hasFilters = !!(debounced || slot !== 'all' || maxMinutes != null || methodCode || pantryMatch);

  const header = (
    <View style={{ gap: space.md, marginBottom: space.md }}>
      <View style={{ gap: 2 }}>
        <T v="huge" accessibilityRole="header">
          Khám phá món Việt
        </T>
        <T tone="muted">Tìm công thức theo nguyên liệu sẵn có trong kho, thời gian nấu và bảng dinh dưỡng từng phần.</T>
      </View>

      <Field
        label="Tìm món"
        testID="explore-search"
        value={search}
        onChangeText={setSearch}
        placeholder="Ví dụ: cá kho, rau muống, canh chua…"
        autoCapitalize="none"
      />

      <View style={{ gap: space.sm }}>
        <Row gap={space.sm}>
          {([
            ['all', 'Tất cả'],
            ['man', 'Mặn'],
            ['rau', 'Rau'],
            ['canh', 'Canh'],
          ] as const).map(([k, lbl]) => (
            <Chip key={k} label={lbl} selected={slot === k} onPress={() => setSlot(k)} />
          ))}
        </Row>

        <Row gap={space.sm}>
          {[20, 30, 45].map((m) => (
            <Chip
              key={m}
              label={`Tối đa ${m} phút`}
              selected={maxMinutes === m}
              onPress={() => setMaxMinutes((cur) => (cur === m ? undefined : m))}
            />
          ))}
          <Chip
            label="Đủ đồ trong kho"
            selected={pantryMatch}
            left={<Icon name="sliders" size={16} color={pantryMatch ? c.accent : c.muted} />}
            onPress={() => setPantryMatch((v) => !v)}
          />
        </Row>

        {ref.data?.cooking_methods?.length ? (
          <Row gap={space.sm}>
            <Chip label="Mọi cách nấu" selected={!methodCode} onPress={() => setMethodCode(undefined)} />
            {ref.data.cooking_methods.slice(0, 6).map((cm) => (
              <Chip
                key={cm.code}
                label={cm.name_vi}
                selected={methodCode === cm.code}
                onPress={() => setMethodCode((cur) => (cur === cm.code ? undefined : cm.code))}
              />
            ))}
          </Row>
        ) : null}
      </View>

      {isOffline ? (
        <Notice tone="info">
          <T>Đang xem từ bộ nhớ đệm ngoại tuyến.</T>
        </Notice>
      ) : null}

      {q.isLoading && !isOffline ? <Loading rows={4} /> : null}
      {q.isError && !isOffline ? <ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} /> : null}
    </View>
  );

  const emptyEl =
    q.isLoading || (q.isError && !isOffline) ? null : items.length === 0 ? (
      <Empty
        title="Không tìm thấy món phù hợp"
        body="Thử bỏ bớt bộ lọc hoặc đổi từ khoá tìm kiếm."
        action={hasFilters ? <Button label="Xoá bộ lọc" kind="secondary" onPress={clearFilters} /> : undefined}
      />
    ) : null;

  const footerEl =
    !isOffline && q.hasNextPage ? (
      <View style={{ paddingTop: space.md, alignItems: 'center' }}>
        <Button
          label="Tải thêm"
          kind="secondary"
          onPress={() => q.fetchNextPage()}
          loading={q.isFetchingNextPage}
        />
      </View>
    ) : null;

  return (
    <Screen testID="screen-explore" scroll={false}>
      <FlatList
        key={cols}
        data={items}
        numColumns={cols}
        keyExtractor={(r) => r.id}
        windowSize={5}
        initialNumToRender={12}
        ListHeaderComponent={header}
        ListEmptyComponent={emptyEl ?? undefined}
        ListFooterComponent={footerEl ?? undefined}
        columnWrapperStyle={cols > 1 ? { gap: space.md } : undefined}
        contentContainerStyle={{ gap: space.md, paddingBottom: space.xxl }}
        renderItem={({ item }) => (
          <RecipeCard
            recipe={item}
            methodName={methodMap.get(item.method_code) ?? item.method_code}
            multiCol={cols > 1}
            onPress={() => router.push({ pathname: '/mon/[id]', params: { id: item.id } })}
          />
        )}
      />
    </Screen>
  );
}
