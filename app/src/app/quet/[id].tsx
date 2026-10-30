import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { api, call, type Schemas } from '@/api/client';
import { goTab } from '@/lib/nav';
import { codeText, errorText } from '@/api/errors';
import { FRESH_LABEL, FreshBadge, type Freshness } from '@/components/domain';
import { IngredientSearch, LEVEL_LABEL } from '@/components/pantryForms';
import { Button, Chip, ErrorBox, Loading, Notice, Radio, Row, Screen, Section, Sheet, Stepper, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { useLots, useReference } from '@/lib/queries';
import { space } from '@/theme';

type Item = Schemas['ScanItem'];
const MERGE = { headers: { 'Content-Type': 'application/merge-patch+json' } };

/** Xác nhận nguyên liệu (UC13): chips by food group, "cần kiểm tra" first, edit / add / delete, confirm into the pantry. */
export default function ConfirmScan() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const ref = useReference();
  const catalog = useCatalog();
  const lots = useLots();
  const [editing, setEditing] = useState<Item | null>(null);
  const [adding, setAdding] = useState(false);
  const [result, setResult] = useState<Schemas['ScanConfirmResult'] | null>(null);

  // long-poll while the job runs (GET /scans/{id}?wait=10)
  const scan = useQuery({
    queryKey: ['scan', id],
    queryFn: () => call(api.GET('/scans/{id}', { params: { path: { id }, query: { wait: 10 } } })),
    refetchInterval: (q) => (q.state.data && ['queued', 'processing'].includes(q.state.data.status) ? 500 : false),
  });
  const reload = () => scan.refetch();

  const confirm = useMutation({
    mutationFn: () =>
      call(
        api.POST('/scans/{id}/confirm', {
          params: { path: { id } },
          body: scan.data?.mode === 'haul' ? { purchase_date: new Date().toISOString().slice(0, 10) } : {},
        }),
      ),
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ['lots'] });
    },
  });
  const discard = useMutation({
    mutationFn: () => call(api.POST('/scans/{id}/discard', { params: { path: { id } } })),
    onSuccess: () => goTab('/bep'),
  });

  if (scan.isLoading) return <Screen><Loading label="Đang tải kết quả quét…" /></Screen>;
  if (scan.error) return <Screen><ErrorBox message={errorText(scan.error)} onRetry={reload} /></Screen>;
  const s = scan.data!;

  if (s.status === 'queued' || s.status === 'processing') {
    return (
      <Screen testID="screen-scan-wait">
        <Loading label={s.status === 'queued' ? 'Ảnh đang chờ xử lý…' : 'Đang nhận diện nguyên liệu…'} />
      </Screen>
    );
  }
  if (s.status === 'failed' || s.status === 'expired') {
    return (
      <Screen>
        <Notice tone="warn">
          <T v="title">Không nhận diện được</T>
          <T>{s.error_code ? codeText(s.error_code) : 'Ảnh chưa xử lý được.'}</T>
        </Notice>
        <Button label="Quét lại" onPress={() => router.replace({ pathname: '/quet', params: { mode: s.mode } })} />
        <Button label="Nhập tay trong Kho" kind="secondary" onPress={() => goTab('/kho')} />
      </Screen>
    );
  }
  if (result || s.status === 'confirmed') {
    return (
      <Screen testID="screen-scan-done">
        <Notice tone="ok">
          <T v="title">Đã đưa vào kho</T>
          {result ? (
            <T>
              {result.created_lot_ids.length} lô mới
              {result.not_seen_lot_ids.length ? `, ${result.not_seen_lot_ids.length} lô lần này không thấy (xác nhận ở Kho)` : ''}.
            </T>
          ) : null}
        </Notice>
        <Button label="Ra mâm cơm" onPress={() => goTab('/mam')} />
        <Button label="Xem kho" kind="secondary" onPress={() => goTab('/kho')} />
      </Screen>
    );
  }

  const live = s.items.filter((i) => i.user_action !== 'deleted');
  const fresh = (i: Item): Freshness => (i.user_freshness ?? i.predicted_freshness ?? 'chua_ro') as Freshness;
  const check = live.filter((i) => i.needs_check && !i.user_freshness);
  const rest = live.filter((i) => !check.includes(i));
  const groupName = (i: Item) => {
    const fg = catalog.ingredients.get(i.ingredient_id)?.food_group_code;
    return ref.data?.food_groups.find((g) => g.code === fg)?.name_vi ?? 'Khác';
  };
  const groups = new Map<string, Item[]>();
  rest.forEach((i) => groups.set(groupName(i), [...(groups.get(groupName(i)) ?? []), i]));
  const seen = new Set(live.map((i) => i.ingredient_id));
  const unseen = s.mode === 'fridge' ? (lots.data?.items ?? []).filter((l) => l.status === 'in_stock' && !seen.has(l.ingredient_id)) : [];

  const chip = (i: Item) => {
    const conf = Math.max(0, ...i.detections.map((d) => d.confidence));
    const low = i.origin === 'model' && conf > 0 && conf < 0.5;
    const qty = i.final_count ?? i.model_count;
    return (
      <View key={i.id} style={{ opacity: low ? 0.7 : 1 }}>
        <Chip
          testID={`scan-chip-${i.ingredient_name_vi}`}
          onPress={() => setEditing(i)}
          label={`${i.ingredient_name_vi}${qty ? ` ×${qty}` : ''}${i.qty_level ? ` · ${LEVEL_LABEL[i.qty_level].toLowerCase()}` : ''}${low ? ' · chưa chắc' : ''}`}
          left={<FreshBadge value={fresh(i)} small />}
        />
      </View>
    );
  };

  return (
    <Screen
      testID="screen-scan-confirm"
      footer={
        <>
          {confirm.error ? <ErrorBox message={errorText(confirm.error)} /> : null}
          <Button label="Đưa vào kho" testID="scan-confirm" onPress={() => confirm.mutate()} loading={confirm.isPending} />
          <Button label="Bỏ kết quả này" kind="ghost" onPress={() => discard.mutate()} />
        </>
      }>
      <T tone="muted">Chạm vào một nguyên liệu để sửa tên, số lượng hoặc độ tươi.</T>
      {check.length ? (
        <Section title="Cần kiểm tra trước khi dùng">
          <T v="small" tone="muted">
            Xem, ngửi thử rồi chọn độ tươi. Tastoria không dùng đồ ở mức này khi ghép mâm.
          </T>
          <Row>{check.map(chip)}</Row>
        </Section>
      ) : null}
      {[...groups.entries()].map(([g, list]) => (
        <Section key={g} title={g}>
          <Row>{list.map(chip)}</Row>
        </Section>
      ))}
      <Button label="+ Thêm nguyên liệu bị sót" kind="secondary" onPress={() => setAdding(true)} />
      {unseen.length ? (
        <Section title="Lần này không thấy">
          <T v="small" tone="muted">
            Sẽ được đánh dấu &quot;chưa thấy&quot;; bạn xác nhận lại ở Kho.
          </T>
          <T>{unseen.map((l) => l.ingredient_name_vi).join(', ')}</T>
        </Section>
      ) : null}
      {editing ? <EditChip scanId={id} item={editing} onClose={() => setEditing(null)} reload={reload} /> : null}
      <AddChip scanId={id} visible={adding} onClose={() => setAdding(false)} reload={reload} />
    </Screen>
  );
}

function EditChip({
  scanId,
  item,
  onClose,
  reload,
}: {
  scanId: string;
  item: Item;
  onClose: () => void;
  reload: () => void;
}) {
  const catalog = useCatalog();
  const ing = catalog.ingredients.get(item.ingredient_id);
  const [count, setCount] = useState(item.final_count ?? item.model_count ?? 1);
  const [level, setLevel] = useState(item.qty_level);
  const [freshness, setFreshness] = useState<Exclude<Freshness, 'chua_ro'> | null>(item.user_freshness ?? null);
  const [relabel, setRelabel] = useState<Schemas['Ingredient'] | null>(null);
  const patch = useMutation({
    mutationFn: (body: Schemas['ScanItemPatch']) =>
      call(api.PATCH('/scans/{id}/items/{itemId}', { params: { path: { id: scanId, itemId: item.id } }, body, ...MERGE })),
    onSuccess: () => {
      reload();
      onClose();
    },
  });
  const del = useMutation({
    mutationFn: () => call(api.DELETE('/scans/{id}/items/{itemId}', { params: { path: { id: scanId, itemId: item.id } } })),
    onSuccess: () => {
      reload();
      onClose();
    },
  });
  const countable = relabel ? relabel.countable : (ing?.countable ?? item.final_count != null);
  const save = () =>
    patch.mutate({
      ...(relabel ? { ingredient_id: relabel.id } : {}),
      ...(countable ? { final_count: count } : { qty_level: level }),
      ...(freshness ? { user_freshness: freshness } : {}),
    });
  return (
    <Sheet visible onClose={onClose} title={item.ingredient_name_vi} testID="sheet-scan-item">
      <Section title="Đổi tên (nếu nhận sai)">
        <IngredientSearch onPick={setRelabel} picked={relabel} />
      </Section>
      {countable ? (
        <Stepper label="Số lượng" value={count} onChange={setCount} min={0} max={99} />
      ) : (
        <View style={{ gap: space.xs }}>
          <T v="label">Lượng</T>
          <Row>
            {(['it', 'vua', 'nhieu'] as const).map((l) => (
              <Radio key={l} label={LEVEL_LABEL[l]} selected={level === l} onPress={() => setLevel(l)} />
            ))}
          </Row>
        </View>
      )}
      <View style={{ gap: space.xs }}>
        <T v="label">Độ tươi</T>
        {(['tuoi', 'dung_som', 'dung_ngay', 'kiem_tra'] as const).map((f) => (
          <Radio key={f} label={FRESH_LABEL[f]} selected={freshness === f} onPress={() => setFreshness(f)} />
        ))}
      </View>
      {patch.error || del.error ? <ErrorBox message={errorText(patch.error ?? del.error)} /> : null}
      <Button label="Lưu" onPress={save} loading={patch.isPending} disabled={!countable && !level} />
      <Button label="Xoá (nhận nhầm)" kind="danger" onPress={() => del.mutate()} loading={del.isPending} />
    </Sheet>
  );
}

function AddChip({ scanId, visible, onClose, reload }: { scanId: string; visible: boolean; onClose: () => void; reload: () => void }) {
  const [ing, setIng] = useState<Schemas['Ingredient'] | null>(null);
  const [count, setCount] = useState(1);
  const [level, setLevel] = useState<'it' | 'vua' | 'nhieu'>('vua');
  const add = useMutation({
    mutationFn: () =>
      call(
        api.POST('/scans/{id}/items', {
          params: { path: { id: scanId } },
          body: { ingredient_id: ing!.id, ...(ing!.countable ? { final_count: count } : { qty_level: level }) },
        }),
      ),
    onSuccess: () => {
      reload();
      setIng(null);
      onClose();
    },
  });
  return (
    <Sheet visible={visible} onClose={onClose} title="Thêm nguyên liệu">
      <IngredientSearch onPick={setIng} picked={ing} />
      {ing ? (
        ing.countable ? (
          <Stepper label="Số lượng" value={count} onChange={setCount} min={1} max={99} />
        ) : (
          <Row>
            {(['it', 'vua', 'nhieu'] as const).map((l) => (
              <Radio key={l} label={LEVEL_LABEL[l]} selected={level === l} onPress={() => setLevel(l)} />
            ))}
          </Row>
        )
      ) : null}
      {add.error ? <ErrorBox message={errorText(add.error)} /> : null}
      <Button label="Thêm" onPress={() => add.mutate()} disabled={!ing} loading={add.isPending} />
    </Sheet>
  );
}
