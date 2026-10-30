import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useState } from 'react';
import { Pressable, View } from 'react-native';

import { api, call, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { fmtG, FreshBadge } from '@/components/domain';
import { daysAgoIso, IngredientSearch, PurchaseDate, QuantityEditor } from '@/components/pantryForms';
import { Button, Card, Empty, ErrorBox, Loading, Notice, Row, Screen, Section, Sheet, T } from '@/components/ui';
import { useLots } from '@/lib/queries';
import { radius, space, useTheme } from '@/theme';

type Lot = Schemas['PantryLot'];
type Qty = Schemas['QuantityInput'];

const MERGE = { headers: { 'Content-Type': 'application/merge-patch+json' } };

function fmtDate(iso: string) {
  const d = new Date(iso);
  return `${d.getDate()}/${d.getMonth() + 1}`;
}

/** Kho theo lô (UC14): list, add by hand, edit amount / date, confirm "kiểm tra" lots, mark used up, discard. */
export default function Pantry() {
  const { c } = useTheme();
  const lots = useLots();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Lot | null>(null);
  const items = lots.data?.items ?? [];
  const check = items.filter((l) => l.freshness_label === 'kiem_tra');

  return (
    <Screen testID="screen-pantry">
      <Button label="Thêm đồ bằng tay" kind="secondary" testID="pantry-add" onPress={() => setAdding(true)} />
      {lots.isLoading ? <Loading rows={4} /> : null}
      {lots.error ? <ErrorBox message={errorText(lots.error)} onRetry={() => lots.refetch()} /> : null}
      {lots.data && items.length === 0 ? (
        <Empty title="Kho đang trống" body="Chụp tủ lạnh ở Trang chủ, hoặc thêm từng món bằng tay." />
      ) : null}
      {check.length ? (
        <Notice tone="warn">
          <T>
            {check.length} lô ở mức &quot;kiểm tra trước khi dùng&quot;. Tastoria không dùng chúng khi ghép mâm cho tới khi bạn xác nhận vẫn dùng được.
          </T>
        </Notice>
      ) : null}
      {items.length ? (
        <Section title={`${items.length} lô trong kho`}>
          <T v="small" tone="muted" style={{ marginTop: -space.sm }}>Đồ cần dùng trước xếp ở trên. Chạm một lô để sửa lượng, ngày mua.</T>
          <View style={{ gap: space.sm }}>
            {items.map((l) => (
              <Pressable key={l.id} accessibilityRole="button" onPress={() => setEditing(l)} testID={`lot-${l.ingredient_name_vi}`}>
                <Card style={{ gap: 6, borderRadius: radius.md, borderLeftWidth: 4, borderLeftColor: c.fresh[l.freshness_label], paddingVertical: space.md }}>
                  <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                    <T v="title" style={{ flexShrink: 1 }}>
                      {l.ingredient_name_vi}
                    </T>
                    <T v="label" style={{ fontVariant: ['tabular-nums'] }}>{fmtG(l.balance_g_min, l.balance_g_max)}</T>
                  </Row>
                  <FreshBadge value={l.freshness_label} small />
                  <T v="small" tone="muted">
                    {l.acquired_basis === 'purchase_date_entered' ? `Mua ${fmtDate(l.acquired_at)}` : `Thấy lần đầu ${fmtDate(l.acquired_at)}`}
                    {l.status === 'not_seen' ? ' · lần quét gần nhất không thấy' : ''}
                  </T>
                </Card>
              </Pressable>
            ))}
          </View>
        </Section>
      ) : null}
      <AddLotSheet visible={adding} onClose={() => setAdding(false)} />
      {editing ? <EditLotSheet lot={editing} onClose={() => setEditing(null)} /> : null}
    </Screen>
  );
}

function AddLotSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [ing, setIng] = useState<Schemas['Ingredient'] | null>(null);
  const [qty, setQty] = useState<Qty | null>(null);
  const [days, setDays] = useState<number | null>(0);
  const onQty = useCallback((q: Qty | null) => setQty(q), []);
  const add = useMutation({
    mutationFn: () =>
      call(
        api.POST('/pantry/lots', {
          body: { ingredient_id: ing!.id, quantity: qty!, ...(days !== null ? { acquired_at: daysAgoIso(days) } : {}) },
        }),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['lots'] });
      setIng(null);
      setQty(null);
      onClose();
    },
  });
  return (
    <Sheet visible={visible} onClose={onClose} title="Thêm đồ vào kho" testID="sheet-add-lot">
      <IngredientSearch onPick={setIng} picked={ing} testID="add-lot-search" />
      {ing ? (
        <>
          <T v="title">{ing.name_vi}</T>
          <QuantityEditor key={ing.id} ingredient={ing} onChange={onQty} />
          <PurchaseDate value={days} onChange={setDays} />
        </>
      ) : null}
      {add.error ? <ErrorBox message={errorText(add.error)} /> : null}
      <Button label="Thêm vào kho" testID="add-lot-submit" onPress={() => add.mutate()} loading={add.isPending} disabled={!ing || !qty} />
    </Sheet>
  );
}

function EditLotSheet({ lot, onClose }: { lot: Lot; onClose: () => void }) {
  const qc = useQueryClient();
  const ing = useQuery({
    queryKey: ['ingredient-of', lot.ingredient_id],
    queryFn: async () => {
      const r = await call(api.GET('/ingredients', { params: { query: { q: lot.ingredient_name_vi, limit: 20 } } }));
      return r.items.find((i) => i.id === lot.ingredient_id) ?? null;
    },
  });
  const [qty, setQty] = useState<Qty | null>(null);
  const [days, setDays] = useState<number | null | undefined>(undefined);
  const onQty = useCallback((q: Qty | null) => setQty(q), []);
  const done = () => {
    qc.invalidateQueries({ queryKey: ['lots'] });
    onClose();
  };
  const patch = useMutation({
    mutationFn: (body: Schemas['PantryLotPatch']) =>
      call(api.PATCH('/pantry/lots/{id}', { params: { path: { id: lot.id } }, body, ...MERGE })),
    onSuccess: done,
  });
  const discard = useMutation({
    mutationFn: () => call(api.POST('/pantry/lots/{id}/discard', { params: { path: { id: lot.id } } })),
    onSuccess: done,
  });
  const err = patch.error ?? discard.error;
  return (
    <Sheet visible onClose={onClose} title={lot.ingredient_name_vi} testID="sheet-edit-lot">
      <Row style={{ justifyContent: 'space-between' }}>
        <FreshBadge value={lot.freshness_label} />
        <T>Còn {fmtG(lot.balance_g_min, lot.balance_g_max)}</T>
      </Row>
      {lot.freshness_label === 'kiem_tra' ? (
        <Notice tone="warn">
          <T>Xem, ngửi thử. Nếu vẫn dùng được, xác nhận để Tastoria tính lô này khi ghép mâm.</T>
          <Button label="Vẫn dùng được" kind="secondary" onPress={() => patch.mutate({ user_checked: true })} loading={patch.isPending} />
        </Notice>
      ) : null}
      {lot.status === 'not_seen' ? (
        <Button label="Vẫn còn trong tủ" kind="secondary" onPress={() => patch.mutate({ status: 'in_stock' })} />
      ) : null}
      <Section title="Sửa lượng còn lại">
        {ing.isLoading ? <Loading /> : ing.data ? <QuantityEditor ingredient={ing.data} onChange={onQty} /> : null}
        <Button label="Lưu lượng" kind="secondary" disabled={!qty} onPress={() => qty && patch.mutate({ balance: qty })} />
      </Section>
      <PurchaseDate value={days ?? null} onChange={setDays} />
      <Button
        label="Lưu ngày mua"
        kind="secondary"
        disabled={days === undefined || days === null}
        onPress={() =>
          typeof days === 'number' && patch.mutate({ acquired_at: daysAgoIso(days), acquired_basis: 'purchase_date_entered' })
        }
      />
      {err ? <ErrorBox message={errorText(err)} /> : null}
      <Row>
        <Button label="Đã dùng hết" kind="secondary" onPress={() => patch.mutate({ status: 'used_up' })} />
        <Button label="Bỏ lô này" kind="danger" testID="lot-discard" onPress={() => discard.mutate()} loading={discard.isPending} />
      </Row>
    </Sheet>
  );
}
