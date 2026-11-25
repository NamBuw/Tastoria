import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { memo, useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, useWindowDimensions, View } from 'react-native';

import { api, call, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { FreshBadge, Icon } from '@/components/domain';
import { AddLotSheet, daysAgoIso, PurchaseDate, QuantityEditor } from '@/components/pantryForms';
import { Button, Card, Chip, Empty, ErrorBox, Field, Loading, Notice, Row, Screen, Section, Sheet, T, UnderlineTabs } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { formatFriendlyQty, groupLotsByIngredient, type GroupedPantryItem, type Ingredient, type Lot } from '@/lib/pantryDisplay';
import { fetchAllPages, qk, useLots } from '@/lib/queries';
import { radius, space, useTheme } from '@/theme';

import { ShoppingListBody } from './di-cho';

type Qty = Schemas['QuantityInput'];
type FilterKey = 'all' | 'dung_ngay' | 'dung_som' | 'tuoi' | 'kiem_tra' | 'not_seen';

const MERGE = { headers: { 'Content-Type': 'application/merge-patch+json' } };

const FILTERS: { key: FilterKey; label: string; testID: string }[] = [
  { key: 'all', label: 'Tất cả', testID: 'pantry-filter-all' },
  { key: 'dung_ngay', label: 'Dùng ngay', testID: 'pantry-filter-dung-ngay' },
  { key: 'dung_som', label: 'Nên dùng sớm', testID: 'pantry-filter-dung-som' },
  { key: 'tuoi', label: 'Tươi', testID: 'pantry-filter-tuoi' },
  { key: 'kiem_tra', label: 'Cần kiểm tra', testID: 'pantry-filter-kiem-tra' },
  { key: 'not_seen', label: 'Chưa thấy gần đây', testID: 'pantry-filter-not-seen' },
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

const GroupCard = memo(function GroupCard({
  item,
  ingredient,
  onPress,
  multiCol,
}: {
  item: GroupedPantryItem;
  ingredient?: Ingredient;
  onPress: (group: GroupedPantryItem) => void;
  multiCol: boolean;
}) {
  const { c } = useTheme();
  const qtyText = formatFriendlyQty(item.balance_g_min, item.balance_g_max, ingredient);
  return (
    <Pressable
      accessibilityRole="button"
      onPress={() => onPress(item)}
      testID={`lot-${item.ingredient_name_vi}`}
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
        <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap', alignItems: 'flex-start' }} gap={space.sm}>
          <T v="title" style={{ flexShrink: 1 }}>
            {item.ingredient_name_vi}
          </T>
          <View style={{ backgroundColor: c.surfaceAlt, paddingHorizontal: 10, paddingVertical: 3, borderRadius: radius.sm }}>
            <T v="label" tabular>
              {qtyText}
            </T>
          </View>
        </Row>
        <Row style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <FreshBadge value={item.freshness_label} small />
          <T v="small" tone="muted" tabular>
            {item.acquired_basis === 'purchase_date_entered' ? `Mua ${fmtDate(item.acquired_at)}` : `Thấy ${fmtDate(item.acquired_at)}`}
            {item.lots.length > 1 ? ` · ${item.lots.length} lần mua` : ''}
          </T>
        </Row>
        {item.hasNotSeen ? (
          <View style={{ backgroundColor: c.warnSoft, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 4, alignSelf: 'flex-start', maxWidth: '100%', flexShrink: 1 }}>
            <T v="small" tone="warn" style={{ flexShrink: 1 }}>
              Chưa thấy khi quét kiểm kê gần nhất
            </T>
          </View>
        ) : null}
        {item.freshness_label === 'kiem_tra' ? (
          <T v="small" tone="accent">
            Chạm để xác nhận còn tươi / dùng được
          </T>
        ) : null}
      </Card>
    </Pressable>
  );
});

/** Tủ lạnh & Đi chợ (UC14 + UC18): nguyên liệu gộp gọn theo tên, đơn vị đời thường, và danh sách đi chợ cùng chỗ. */
export default function Pantry() {
  const { c } = useTheme();
  const router = useRouter();
  const { status } = useSession();
  const catalog = useCatalog();
  const { width } = useWindowDimensions();
  const cols = width >= 1024 ? 3 : width >= 768 ? 2 : 1;
  const [subTab, setSubTab] = useState<'fridge' | 'shopping'>('fridge');
  const [sort, setSort] = useState<'urgency' | 'created_at'>('urgency');
  const lots = useLots(sort);
  const shopping = useQuery({
    queryKey: qk.shopping,
    enabled: status === 'signedIn',
    queryFn: () =>
      fetchAllPages((cursor) =>
        call(api.GET('/shopping-items', { params: { query: { status: ['open', 'bought'], cursor, limit: 100 } } })),
      ),
  });
  const [filter, setFilter] = useState<FilterKey>('all');
  const [search, setSearch] = useState('');
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<GroupedPantryItem | null>(null);

  const items = useMemo(() => lots.data?.items ?? [], [lots.data]);
  const grouped = useMemo(() => groupLotsByIngredient(items), [items]);
  const openShopCount = useMemo(
    () => (shopping.data?.items ?? []).filter((s) => s.status === 'open').length,
    [shopping.data],
  );
  const checkCount = useMemo(() => grouped.filter((g) => g.freshness_label === 'kiem_tra').length, [grouped]);

  const filtered = useMemo(() => {
    const q = norm(search.trim());
    return grouped.filter((g) => {
      if (filter === 'not_seen' && !g.hasNotSeen) return false;
      if (filter !== 'all' && filter !== 'not_seen' && g.freshness_label !== filter) return false;
      if (q && !norm(g.ingredient_name_vi).includes(q)) return false;
      return true;
    });
  }, [grouped, filter, search]);

  const gridData = useMemo<(GroupedPantryItem | { kind: 'spacer'; id: string })[]>(() => {
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
            Tủ lạnh &amp; Đi chợ
          </T>
          {lots.data ? (
            <T v="small" tone="muted" tabular>
              Đang có {filtered.length}/{grouped.length} nguyên liệu · {sort === 'urgency' ? 'sắp hỏng lên trước' : 'mới thêm trước'}
            </T>
          ) : null}
        </View>
        <Row gap={space.sm}>
          <Button
            label="Quét ảnh"
            kind="secondary"
            testID="pantry-scan"
            icon={<Icon name="camera" size={18} color={c.accent} />}
            onPress={() => router.push({ pathname: '/quet', params: { mode: 'haul' } })}
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

      <UnderlineTabs
        label="Chế độ xem"
        options={[
          ['fridge', `Trong tủ (${grouped.length})`, 'pantry-tab-fridge'],
          ['shopping', `Cần đi chợ${openShopCount ? ` (${openShopCount})` : ''}`, 'pantry-tab-shopping'],
        ]}
        value={subTab}
        onChange={setSubTab}
      />

      <Row style={{ alignItems: 'flex-end' }} gap={space.md}>
        <View style={{ flex: 1, minWidth: 200 }}>
          <Field
            label="Tìm nguyên liệu trong tủ"
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
          label={sort === 'urgency' ? 'Sắp xếp: Sắp hỏng trước' : 'Sắp xếp: Mới thêm'}
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
            Có {checkCount} nguyên liệu cần kiểm tra trước khi nấu. Hệ thống tạm không đưa vào gợi ý cho tới khi bạn xác nhận còn dùng được.
          </T>
        </Notice>
      ) : null}

      {lots.isLoading ? <Loading rows={4} /> : null}
      {lots.error ? <ErrorBox message={errorText(lots.error)} onRetry={() => lots.refetch()} /> : null}
    </View>
  );

  const emptyEl = lots.isLoading ? null : lots.data && grouped.length === 0 ? (
    <Empty
      title="Tủ lạnh đang trống"
      body="Chụp nhanh thực phẩm vừa mua hoặc chọn tay những món thường có sẵn để bắt đầu nhận gợi ý nấu ăn."
      action={
        <Row gap={space.sm}>
          <Button label="Chụp đồ trong tủ" onPress={() => router.push({ pathname: '/quet', params: { mode: 'haul' } })} />
          <Button label="Thêm bằng tay" kind="secondary" onPress={() => setAdding(true)} />
        </Row>
      }
    />
  ) : lots.data && filtered.length === 0 ? (
    <Empty
      title="Không có nguyên liệu nào phù hợp"
      body="Thử xoá từ khoá tìm kiếm hoặc chuyển bộ lọc về Tất cả."
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

  if (subTab === 'shopping') {
    return (
      <Screen testID="screen-pantry">
        <Row style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <View style={{ flexShrink: 1, gap: 2 }}>
            <T v="huge" accessibilityRole="header">
              Tủ lạnh &amp; Đi chợ
            </T>
            <T v="small" tone="muted" tabular>
              {openShopCount ? `Còn ${openShopCount} món cần mua` : 'Danh sách đi chợ'}
            </T>
          </View>
          <Button
            label="Quay lại Tủ lạnh"
            kind="secondary"
            onPress={() => setSubTab('fridge')}
          />
        </Row>
        <UnderlineTabs
          label="Chế độ xem"
          options={[
            ['fridge', `Trong tủ (${grouped.length})`, 'pantry-tab-fridge'],
            ['shopping', `Cần đi chợ${openShopCount ? ` (${openShopCount})` : ''}`, 'pantry-tab-shopping'],
          ]}
          value={subTab}
          onChange={setSubTab}
        />
        <ShoppingListBody showPageTitle={false} />
      </Screen>
    );
  }

  return (
    <Screen testID="screen-pantry" scroll={false}>
      <FlatList
        key={cols}
        data={gridData}
        numColumns={cols}
        keyExtractor={(l) => ('kind' in l ? l.id : l.ingredient_id)}
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
            <GroupCard
              item={item as GroupedPantryItem}
              ingredient={catalog.ingredients.get((item as GroupedPantryItem).ingredient_id)}
              onPress={setEditing}
              multiCol={cols > 1}
            />
          )
        }
      />
      <AddLotSheet visible={adding} onClose={() => setAdding(false)} />
      {editing ? <EditGroupSheet group={editing} onClose={() => setEditing(null)} /> : null}
    </Screen>
  );
}

function EditGroupSheet({ group, onClose }: { group: GroupedPantryItem; onClose: () => void }) {
  const qc = useQueryClient();
  const catalog = useCatalog();
  const primary = group.primaryLot;
  const cachedIng = catalog.ingredients.get(group.ingredient_id);
  const ing = useQuery({
    queryKey: ['ingredient-of', group.ingredient_id],
    enabled: !cachedIng,
    queryFn: async () => {
      const r = await call(api.GET('/ingredients', { params: { query: { q: group.ingredient_name_vi, limit: 20 } } }));
      return r.items.find((i) => i.id === group.ingredient_id) ?? null;
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

  const patchOne = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas['PantryLotPatch'] }) =>
      call(api.PATCH('/pantry/lots/{id}', { params: { path: { id } }, body, ...MERGE })),
    onSuccess: done,
  });

  const patchTargets = useMutation({
    mutationFn: async ({ targets, body }: { targets: Lot[]; body: Schemas['PantryLotPatch'] }) => {
      await Promise.all(
        targets.map((l) => call(api.PATCH('/pantry/lots/{id}', { params: { path: { id: l.id } }, body, ...MERGE }))),
      );
    },
    onSuccess: done,
  });

  const discardAll = useMutation({
    mutationFn: async () => {
      await Promise.all(group.lots.map((l) => call(api.POST('/pantry/lots/{id}/discard', { params: { path: { id: l.id } } }))));
    },
    onSuccess: done,
  });

  const err = patchOne.error ?? patchTargets.error ?? discardAll.error;
  const friendlyTotal = formatFriendlyQty(group.balance_g_min, group.balance_g_max, resolvedIng);

  return (
    <Sheet visible onClose={onClose} title={group.ingredient_name_vi} testID="sheet-edit-lot">
      <Row style={{ justifyContent: 'space-between' }}>
        <FreshBadge value={group.freshness_label} />
        <T tabular>Hiện còn {friendlyTotal}</T>
      </Row>
      {group.lots.length > 1 ? (
        <Notice tone="info">
          <T v="small">
            Đang gộp từ {group.lots.length} lần thêm vào tủ ({group.lots.map((l) => `${fmtDate(l.acquired_at)}`).join(', ')}).
          </T>
        </Notice>
      ) : null}
      {group.freshness_label === 'kiem_tra' ? (
        <Notice tone="warn">
          <T>Xem, ngửi thử. Nếu vẫn dùng được, xác nhận để hệ thống đưa vào gợi ý nấu ăn.</T>
          <Button
            label="Xác nhận còn tươi / dùng được"
            kind="secondary"
            testID="lot-confirm-fresh"
            onPress={() =>
              patchTargets.mutate({
                targets: group.lots.filter((l) => l.freshness_label === 'kiem_tra'),
                body: { user_checked: true },
              })
            }
            loading={patchTargets.isPending}
          />
        </Notice>
      ) : null}
      {group.hasNotSeen ? (
        <Notice tone="warn">
          <T>Nguyên liệu này không thấy trong lần chụp kiểm kê gần nhất.</T>
          <Button
            label="Xác nhận vẫn còn trong tủ"
            kind="secondary"
            testID="lot-confirm-seen"
            onPress={() =>
              patchTargets.mutate({
                targets: group.lots.filter((l) => l.status === 'not_seen'),
                body: { status: 'in_stock' },
              })
            }
            loading={patchTargets.isPending}
          />
        </Notice>
      ) : null}
      <Section title="Cập nhật lượng còn lại">
        {!cachedIng && ing.isLoading ? <Loading /> : resolvedIng ? <QuantityEditor ingredient={resolvedIng} onChange={onQty} /> : null}
        <Button label="Lưu lượng" kind="secondary" disabled={!qty} onPress={() => qty && patchOne.mutate({ id: primary.id, body: { balance: qty } })} />
      </Section>
      <PurchaseDate value={days ?? null} onChange={setDays} />
      <Button
        label="Lưu ngày mua"
        kind="secondary"
        disabled={days === undefined || days === null}
        onPress={() =>
          typeof days === 'number' &&
          patchOne.mutate({ id: primary.id, body: { acquired_at: daysAgoIso(days), acquired_basis: 'purchase_date_entered' } })
        }
      />
      {err ? <ErrorBox message={errorText(err)} /> : null}
      <Row>
        <Button
          label="Đã dùng hết"
          kind="secondary"
          onPress={() => patchTargets.mutate({ targets: group.lots, body: { status: 'used_up' } })}
        />
        <Button
          label="Vứt bỏ (đã hỏng)"
          kind="danger"
          testID="lot-discard"
          onPress={() => discardAll.mutate()}
          loading={discardAll.isPending}
        />
      </Row>
    </Sheet>
  );
}
