import { useQuery } from '@tanstack/react-query';
import { useLocalSearchParams, useNavigation } from 'expo-router';
import { useEffect, useRef } from 'react';
import { View } from 'react-native';

import { api, call } from '@/api/client';
import { errorText } from '@/api/errors';
import { Card, ErrorBox, Loading, Row, Screen, Section, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { enqueueEvents } from '@/lib/outbox';
import { useHasConsent, useReference } from '@/lib/queries';
import { space } from '@/theme';

/** Recipe detail (GET /recipes/{id}, falls back to the stored catalog offline); sends `viewed` with consent. */
export default function RecipeDetail() {
  const { id, plan, item } = useLocalSearchParams<{ id: string; plan?: string; item?: string }>();
  const nav = useNavigation();
  const personalization = useHasConsent('personalization');
  const catalog = useCatalog();
  const ref = useReference();
  const q = useQuery({
    queryKey: ['recipe', id],
    queryFn: async () => {
      try {
        return await call(api.GET('/recipes/{id}', { params: { path: { id } } }));
      } catch (e) {
        const cached = catalog.recipes.get(id);
        if (cached) return cached;
        throw e;
      }
    },
  });
  const sent = useRef(false);
  useEffect(() => {
    if (q.data) nav.setOptions({ title: q.data.name_vi });
    if (q.data && personalization && !sent.current) {
      sent.current = true;
      void enqueueEvents([{ type: 'viewed', recipe_id: id, meal_plan_id: plan ?? null, meal_plan_item_id: item ?? null }]);
    }
  }, [q.data, personalization, id, plan, item, nav]);

  if (q.isLoading) return <Screen><Loading /></Screen>;
  if (q.error || !q.data) return <Screen><ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} /></Screen>;
  const r = q.data;
  return (
    <Screen testID="screen-recipe">
      <T v="h1" accessibilityRole="header">
        {r.name_vi}
      </T>
      <T tone="muted">
        {r.servings} người · khoảng {r.total_minutes} phút{r.kcal_per_serving ? ` · ${Math.round(r.kcal_per_serving)} kcal/người` : ''}
      </T>
      {r.make_ahead ? (
        <Card>
          <T>
            Cần có sẵn {r.make_ahead.item_name_vi} (làm từ trước{r.make_ahead.whole_dish ? '' : `, bước 1–${r.make_ahead.through_step_no}`}); lịch nấu
            chỉ tính phần còn lại.
          </T>
        </Card>
      ) : null}
      <Section title="Nguyên liệu">
        <Card style={{ gap: space.xs }}>
          {r.ingredients.map((i) => (
            <Row key={i.ingredient_id} style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
              <T style={{ flexShrink: 1 }}>
                {i.name_vi}
                {i.is_optional ? ' (tuỳ chọn)' : ''}
              </T>
              <T v="label">{Math.round(i.grams)} g</T>
            </Row>
          ))}
        </Card>
      </Section>
      <Section title="Các bước">
        {r.steps.map((s) => (
          <View key={s.step_no} style={{ flexDirection: 'row', gap: space.md }}>
            <T v="title" style={{ width: 28 }}>
              {s.step_no}.
            </T>
            <View style={{ flex: 1 }}>
              <T>{s.text_vi}</T>
              <T v="small" tone="muted">
                {s.minutes} phút · {s.kind === 'active' ? 'đứng bếp' : 'chờ'}
                {s.uses_burner ? ' · dùng bếp' : ''}
              </T>
            </View>
          </View>
        ))}
      </Section>
      {r.nutrition.length ? (
        <Section title="Dinh dưỡng mỗi người">
          <Card style={{ gap: space.xs }}>
            {r.nutrition.map((n) => {
              const meta = ref.data?.nutrients.find((x) => x.code === n.nutrient_code);
              return (
                <Row key={n.nutrient_code} style={{ justifyContent: 'space-between' }}>
                  <T>{meta?.name_vi ?? n.nutrient_code}</T>
                  <T v="label">
                    {Math.round(n.per_serving * 10) / 10} {meta?.unit ?? ''}
                  </T>
                </Row>
              );
            })}
            <T v="small" tone="muted">
              Tính từ bảng thành phần thực phẩm; phiên bản dữ liệu {r.nutrition_data_version ?? 'chưa rõ'}.
            </T>
          </Card>
        </Section>
      ) : null}
      {r.sources.length ? (
        <Section title="Nguồn công thức">
          {r.sources.map((s, i) => (
            <T key={i} v="small" tone="muted">
              {s.title} ({s.url})
            </T>
          ))}
        </Section>
      ) : null}
    </Screen>
  );
}
