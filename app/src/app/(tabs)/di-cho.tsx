import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';

import { api, call, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { IngredientSearch } from '@/components/pantryForms';
import { Button, Card, Checkbox, Empty, ErrorBox, Field, Loading, Row, Screen, Section, Sheet, T } from '@/components/ui';
import { qk } from '@/lib/queries';
import { space } from '@/theme';

const MERGE = { headers: { 'Content-Type': 'application/merge-patch+json' } };

/** Danh sách đi chợ (UC18). */
export default function Shopping() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: qk.shopping,
    queryFn: () => call(api.GET('/shopping-items', { params: { query: { status: ['open', 'bought'], limit: 100 } } })),
  });
  const [adding, setAdding] = useState(false);
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas['ShoppingItemPatch'] }) =>
      call(api.PATCH('/shopping-items/{id}', { params: { path: { id } }, body, ...MERGE })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.shopping }),
  });
  const items = list.data?.items ?? [];
  const open = items.filter((i) => i.status === 'open');
  const bought = items.filter((i) => i.status === 'bought');

  return (
    <Screen testID="screen-shopping">
      <Button label="Thêm đồ cần mua" testID="shop-add" onPress={() => setAdding(true)} />
      {list.isLoading ? <Loading /> : null}
      {list.error ? <ErrorBox message={errorText(list.error)} onRetry={() => list.refetch()} /> : null}
      {patch.error ? <ErrorBox message={errorText(patch.error)} /> : null}
      {list.data && !items.length ? (
        <Empty title="Danh sách trống" body='Thêm đồ ở đây, hoặc từ "Thiếu gì?" trong Mâm cơm hôm nay.' />
      ) : null}
      {open.length ? (
        <Section title={`Cần mua (${open.length})`}>
          <Card style={{ gap: 0 }}>
            {open.map((i) => (
              <View key={i.id}>
                <Checkbox
                  testID={`shop-item-${i.ingredient_name_vi}`}
                  checked={false}
                  onChange={() => patch.mutate({ id: i.id, body: { status: 'bought' } })}
                  label={i.ingredient_name_vi}
                  sub={
                    <T v="small" tone="muted">
                      {[i.qty_g ? `khoảng ${Math.round(i.qty_g)} g` : null, i.note, i.source_meal_plan_item_id ? 'cho mâm hôm nay' : null]
                        .filter(Boolean)
                        .join(' · ') || 'chưa ghi lượng'}
                    </T>
                  }
                />
                <Row style={{ justifyContent: 'flex-end', marginTop: -space.sm }}>
                  <Button kind="ghost" label="Bỏ khỏi danh sách" onPress={() => patch.mutate({ id: i.id, body: { status: 'dropped' } })} />
                </Row>
              </View>
            ))}
          </Card>
        </Section>
      ) : null}
      {bought.length ? (
        <Section title={`Đã mua (${bought.length})`}>
          <T v="small" tone="muted">
            Đồ đã mua chưa tự vào kho. Chụp "đồ vừa mua" ở Trang chủ hoặc thêm trong Kho.
          </T>
          <Card style={{ gap: 0 }}>
            {bought.map((i) => (
              <Checkbox
                key={i.id}
                checked
                onChange={() => patch.mutate({ id: i.id, body: { status: 'open' } })}
                label={i.ingredient_name_vi}
              />
            ))}
          </Card>
        </Section>
      ) : null}
      <AddSheet visible={adding} onClose={() => setAdding(false)} />
    </Screen>
  );
}

function AddSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [ing, setIng] = useState<Schemas['Ingredient'] | null>(null);
  const [grams, setGrams] = useState('');
  const [note, setNote] = useState('');
  const add = useMutation({
    mutationFn: () =>
      call(
        api.POST('/shopping-items', {
          body: { ingredient_id: ing!.id, qty_g: grams ? Number(grams) : null, note: note.trim() || null },
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
      <Field label="Khoảng bao nhiêu gam (không bắt buộc)" value={grams} onChangeText={(v) => setGrams(v.replace(/[^0-9]/g, ''))} keyboardType="number-pad" inputMode="numeric" />
      <Field label="Ghi chú (không bắt buộc)" value={note} onChangeText={setNote} maxLength={500} />
      {add.error ? <ErrorBox message={errorText(add.error)} /> : null}
      <Button label="Thêm" onPress={() => add.mutate()} disabled={!ing} loading={add.isPending} />
    </Sheet>
  );
}
