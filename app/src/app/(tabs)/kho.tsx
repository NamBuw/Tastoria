import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { memo, useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, useWindowDimensions, View } from 'react-native';

import { api, call, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { fmtG, FreshBadge, Icon } from '@/components/domain';
import { AddLotSheet, daysAgoIso, PurchaseDate, QuantityEditor } from '@/components/pantryForms';
import { Button, Card, Chip, Empty, ErrorBox, Field, Loading, Notice, Row, Screen, Section, Sheet, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { useLots } from '@/lib/queries';
import { radius, space, useTheme } from '@/theme';

type Lot = Schemas['PantryLot'];
type Qty = Schemas['QuantityInput'];
type FilterKey = 'all' | 'dung_ngay' | 'dung_som' | 'tuoi' | 'kiem_tra' | 'not_seen';

const MERGE = { headers: { 'Content-Type': 'application/merge-patch+json' } };

const FILTERS: { key: FilterKey; label: string; testID: string }[] = [
  { key: 'all', label: 'Tất cả', testID: 'pantry-filter-all' },
  { key: 'dung_ngay', label: 'Dùng ngay', testID: 'pantry-filter-dung-ngay' },
  { key: 'dung_som', label: 'Nên dùng sớm', testID: 'pantry-filter-dung-som' },
  { key: 'tuoi', label: 'Tươi', testID: 'pantry-filter-tuoi' },
  { key: 'kiem_tra', label: 'Cần kiểm tra', testID: 'pantry-filter-kiem-tra' },
  { key: 'not_seen', label: 'Chưa thấy', testID: 'pantry-filter-not-seen' },
];

function fmtDate(iso: string) {
  const d = new Date(iso);
  return `${d.getDate()}/${d.getMonth() + 1}`;
}

function norm(s: string) {
  return s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd');
}

const LotCard = memo(function LotCard({
  lot,
  onPress,
  multiCol,
}: {
  lot: Lot;
  onPress: (lot: Lot) => void;
  multiCol: boolean;
}) {
  const { c } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={() => onPress(lot)}
      testID={`lot-${lot.ingredient_name_vi}`}
      style={({ pressed }) => [
        multiCol ? { flex: 1, minWidth: 0 } : undefined,
        { opacity: pressed ? 0.9 : 1 },
      ]}>
      <Card
        style={{
          gap: space.sm,
          borderRadius: radius.md,
          padding: space.lg,
          flex: multiCol ? 1 : undefined,
          justifyContent: 'space-between',
        }}>
        <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap', alignItems: 'flex-start' }}>
          <T v="title" style={{ flexShrink: 1 }}>
            {lot.ingredient_name_vi}
          </T>
          <View style={{ backgroundColor: c.surfaceAlt, paddingHorizontal: 10, paddingVertical: 3, borderRadius: radius.sm }}>
            <T v="label" tabular>
              {fmtG(lot.balance_g_min, lot.balance_g_max)}
            </T>
          </View>
        </Row>
        <Row style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <FreshBadge value={lot.freshness_label} small />
          <T v="small" tone="muted" tabular>
            {lot.acquired_basis === 'purchase_date_entered' ? `Mua ${fmtDate(lot.acquired_at)}` : `Thấy ${fmtDate(lot.acquired_at)}`}
          </T>
        </Row>
        {lot.status === 'not_seen' ? (
          <View style={{ backgroundColor: c.warnSoft, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 4, alignSelf: 'flex-start', maxWidth: '100%', flexShrink: 1 }}>
            <T v="small" tone="warn" style={{ flexShrink: 1 }}>
              Chưa thấy trong lần quét gần nhất
            </T>
          </View>
        ) : null}
        {lot.freshness_label === 'kiem_tra' ? (
          <T v="small" tone="accent">
            Chạm để xác nhận còn tươi / dùng được
          </T>
        ) : null}
      </Card>
    </Pressable>
  );
});

/** Kho theo lô (UC14): urgency filters, search/sort, virtualized grid, quick-add, edit/confirm/discard. */
export default function Pantry() {
  const { c } = useTheme();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const cols = width >= 1024 ? 3 : width >= 768 ? 2 : 1;
  const [sort, setSort] = useState<'urgency' | 'created_at'>('urgency');
  const lots = useLots(sort);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [search, setSearch] = useState('');
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Lot | null>(null);

  const items = useMemo(() => lots.data?.items ?? [], [lots.data]);
  const checkCount = useMemo(() => items.filter((l) => l.freshness_label === 'kiem_tra').length, [items]);

  const filtered = useMemo(() => {
    const q = norm(search.trim());
    return items.filter((l) => {
      if (filter === 'not_seen' && l.status !== 'not_seen') return false;
      if (filter !== 'all' && filter !== 'not_seen' && l.freshness_label !== filter) return false;
      if (q && !norm(l.ingredient_name_vi).includes(q)) return false;
      return true;
    });
  }, [items, filter, search]);

  const gridData = useMemo<(Lot | { kind: 'spacer'; id: string })[]>(() => {
    if (cols <= 1 || filtered.length === 0) return filtered;
    const rem = filtered.length % cols;
    if (rem === 0) return filtered;
    const spacers = Array.from({ length: cols - rem }, (_, idx) => ({ kind: 'spacer' as const, id: `spacer-${idx}` }));
    return [...filtered, ...spacers];
  }, [filtered, cols]);

  const header = (
    <View style={{ gap: space.md, marginBottom: space.md }}>
      <Row style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <View style={{ flexShrink: 1, gap: 2 }}>
          <T v="huge" accessibilityRole="header">
            Kho bếp
          </T>
          {lots.data ? (
            <T v="small" tone="muted" tabular>
              Hiển thị {filtered.length}/{items.length} lô, {sort === 'urgency' ? 'ưu tiên dùng trước' : 'mới thêm trước'}
            </T>
          ) : null}
        </View>
        <Row gap={space.sm}>
          <Button
            label="Quét ảnh"
            kind="secondary"
            testID="pantry-scan"
            icon={<Icon name="camera" size={18} color={c.accent} />}
            onPress={() => router.push({ pathname: '/quet', params: { mode: 'fridge' } })}
            style={{ paddingHorizontal: space.md }}
          />
          <Button
            label="Thêm đồ"
            kind="primary"
            testID="pantry-add"
            icon={<Icon name="plus" size={18} color={c.onAccent} />}
            onPress={() => setAdding(true)}
            style={{ paddingHorizontal: space.lg }}
          />
        </Row>
      </Row>

      <Row style={{ alignItems: 'flex-end' }} gap={space.md}>
        <View style={{ flex: 1, minWidth: 200 }}>
          <Field
            label="Tìm nguyên liệu trong kho"
            testID="pantry-search"
            value={search}
            onChangeText={setSearch}
            placeholder="Ví dụ: cà chua, trứng gà, đậu phụ…"
            autoCapitalize="none"
          />
        </View>
        <Button
          kind="secondary"
          testID="pantry-sort"
          label={sort === 'urgency' ? 'Sắp: Khẩn cấp nhất' : 'Sắp: Mới thêm'}
          onPress={() => setSort((s) => (s === 'urgency' ? 'created_at' : 'urgency'))}
          style={{ paddingHorizontal: space.md }}
        />
      </Row>

      <Row gap={space.sm}>
        {FILTERS.map((f) => (
          <Chip
            key={f.key}
            testID={f.testID}
            label={f.label}
            selected={filter === f.key}
            onPress={() => setFilter(f.key)}
          />
        ))}
      </Row>

      {checkCount ? (
        <Notice tone="warn">
          <T>
            Có {checkCount} lô ở mức &quot;kiểm tra trước khi dùng&quot;. Mỹ Vị tạm thời không đưa các lô này vào mâm gợi ý cho tới khi bạn xác nhận còn dùng được.
          </T>
        </Notice>
      ) : null}

      {lots.isLoading ? <Loading rows={4} /> : null}
      {lots.error ? <ErrorBox message={errorText(lots.error)} onRetry={() => lots.refetch()} /> : null}
    </View>
  );

  const emptyEl = lots.isLoading ? null : lots.data && items.length === 0 ? (
    <Empty
      title="Kho đang trống"
      body="Chụp ảnh ngăn tủ lạnh để nhận diện nhanh nguyên liệu sẵn có, hoặc thêm từng món bằng tay."
      action={
        <Row gap={space.sm}>
          <Button label="Quét tủ lạnh" onPress={() => router.push({ pathname: '/quet', params: { mode: 'fridge' } })} />
          <Button label="Thêm bằng tay" kind="secondary" onPress={() => setAdding(true)} />
        </Row>
      }
    />
  ) : lots.data && filtered.length === 0 ? (
    <Empty
      title="Không có nguyên liệu nào phù hợp"
      body="Thử xoá từ khoá tìm kiếm hoặc chuyển bộ lọc về Tất cả mức độ tươi."
      action={
        <Button
          label="Xoá bộ lọc"
          kind="secondary"
          onPress={() => {
            setFilter('all');
            setSearch('');
          }}
        />
      }
    />
  ) : null;

  return (
    <Screen testID="screen-pantry" scroll={false}>
      <FlatList
        key={cols}
        data={gridData}
        numColumns={cols}
        keyExtractor={(l) => l.id}
        windowSize={5}
        initialNumToRender={12}
        ListHeaderComponent={header}
        ListEmptyComponent={emptyEl ?? undefined}
        columnWrapperStyle={cols > 1 ? { gap: space.md } : undefined}
        contentContainerStyle={{ gap: space.md, paddingBottom: space.xxl }}
        renderItem={({ item }) =>
          'kind' in item && item.kind === 'spacer' ? (
            <View style={{ flex: 1, minWidth: 0 }} pointerEvents="none" />
          ) : (
            <LotCard lot={item as Lot} onPress={setEditing} multiCol={cols > 1} />
          )
        }
      />
      <AddLotSheet visible={adding} onClose={() => setAdding(false)} />
      {editing ? <EditLotSheet lot={editing} onClose={() => setEditing(null)} /> : null}
    </Screen>
  );
}

function EditLotSheet({ lot, onClose }: { lot: Lot; onClose: () => void }) {
  const qc = useQueryClient();
  const catalog = useCatalog();
  const cachedIng = catalog.ingredients.get(lot.ingredient_id);
  const ing = useQuery({
    queryKey: ['ingredient-of', lot.ingredient_id],
    enabled: !cachedIng,
    queryFn: async () => {
      const r = await call(api.GET('/ingredients', { params: { query: { q: lot.ingredient_name_vi, limit: 20 } } }));
      return r.items.find((i) => i.id === lot.ingredient_id) ?? null;
    },
  });
  const resolvedIng = cachedIng ?? ing.data ?? null;
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
        <T tabular>Còn {fmtG(lot.balance_g_min, lot.balance_g_max)}</T>
      </Row>
      {lot.freshness_label === 'kiem_tra' ? (
        <Notice tone="warn">
          <T>Xem, ngửi thử. Nếu vẫn dùng được, xác nhận để Mỹ Vị tính lô này khi ghép mâm.</T>
          <Button
            label="Xác nhận còn tươi / dùng được"
            kind="secondary"
            testID="lot-confirm-fresh"
            onPress={() => patch.mutate({ user_checked: true })}
            loading={patch.isPending}
          />
        </Notice>
      ) : null}
      {lot.status === 'not_seen' ? (
        <Notice tone="warn">
          <T>Nguyên liệu này không thấy trong lần quét gần nhất.</T>
          <Button
            label="Xác nhận vẫn còn trong tủ"
            kind="secondary"
            testID="lot-confirm-seen"
            onPress={() => patch.mutate({ status: 'in_stock' })}
            loading={patch.isPending}
          />
        </Notice>
      ) : null}
      <Section title="Sửa lượng còn lại">
        {!cachedIng && ing.isLoading ? <Loading /> : resolvedIng ? <QuantityEditor ingredient={resolvedIng} onChange={onQty} /> : null}
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
