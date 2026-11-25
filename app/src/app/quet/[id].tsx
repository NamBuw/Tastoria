import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';

import { api, call, type Schemas } from '@/api/client';
import { codeText, errorText } from '@/api/errors';
import { FRESH_LABEL, FreshBadge, type Freshness } from '@/components/domain';
import { IngredientSearch, LEVEL_LABEL } from '@/components/pantryForms';
import { Button, Card, Chip, ErrorBox, Loading, Notice, Row, Screen, Section, Segmented, Sheet, Stepper, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { goTab } from '@/lib/nav';
import { UNIT_LABEL } from '@/lib/pantryDisplay';
import { useLots, useReference } from '@/lib/queries';
import { radius, size, space, TOUCH, useLayout, useTheme } from '@/theme';

const LEVELS = (['it', 'vua', 'nhieu'] as const).map((l) => [l, LEVEL_LABEL[l]] as const);

type Detection = Schemas['Detection'] & {
  sub_species_slug?: string | null;
  sub_species_conf?: number | null;
  safety_abstained?: boolean | null;
  safety_note_vi?: string | null;
  label_vi?: string | null;
};
type Item = Omit<Schemas['ScanItem'], 'detections'> & {
  detections: Detection[];
  sub_species_slug?: string | null;
  sub_species_conf?: number | null;
  safety_abstained?: boolean | null;
  safety_note_vi?: string | null;
  label_vi?: string | null;
};
const MERGE = { headers: { 'Content-Type': 'application/merge-patch+json' } };

const MUSHROOM_ABSTAIN_NOTE_VI =
  'Nấm (chưa rõ loại, chỉ dùng nấm rõ nguồn gốc mua tại chợ hoặc siêu thị)';

const MUSHROOM_SUBSPECIES_VI: Record<string, string> = {
  'nam-rom': 'Nấm rơm',
  'nam-huong-tuoi': 'Nấm hương tươi',
  'nam-kim-cham': 'Nấm kim châm',
  'nam-dui-ga': 'Nấm đùi gà',
  'nam-so': 'Nấm sò',
  'nam-mo': 'Nấm mỡ',
};

function isMushroomItem(item: Item, det?: Detection): boolean {
  const baseName = item.ingredient_name_vi.trim().toLowerCase();
  const label = (det?.label_vi ?? item.label_vi ?? '').trim().toLowerCase();
  return (
    baseName === 'nấm' ||
    label.startsWith('nấm') ||
    Boolean(det?.sub_species_slug ?? item.sub_species_slug) ||
    Boolean(det?.safety_abstained ?? item.safety_abstained) ||
    item.detections.some((x) => Boolean(x.sub_species_slug || x.safety_abstained))
  );
}

function resolveMushroomSubspecies(
  item: Item,
  det?: Detection,
): { speciesVi: string | null; conf: number | null; abstained: boolean; safetyNoteVi: string | null } {
  const abstained = Boolean(
    det?.safety_abstained ??
      item.safety_abstained ??
      item.detections.some((x) => x.safety_abstained === true),
  );
  const rawNote =
    det?.safety_note_vi ??
    item.safety_note_vi ??
    item.detections.find((x) => x.safety_note_vi)?.safety_note_vi ??
    null;
  const slug =
    det?.sub_species_slug ??
    item.sub_species_slug ??
    item.detections.find((x) => x.sub_species_slug)?.sub_species_slug ??
    null;

  if (abstained || (isMushroomItem(item, det) && (!slug || !MUSHROOM_SUBSPECIES_VI[slug]))) {
    return {
      speciesVi: null,
      conf: null,
      abstained: true,
      safetyNoteVi: rawNote && rawNote.trim() ? rawNote.trim() : MUSHROOM_ABSTAIN_NOTE_VI,
    };
  }

  if (!slug || !MUSHROOM_SUBSPECIES_VI[slug]) {
    return { speciesVi: null, conf: null, abstained: false, safetyNoteVi: null };
  }
  const conf =
    det?.sub_species_conf ??
    item.sub_species_conf ??
    item.detections.find((x) => x.sub_species_slug === slug)?.sub_species_conf ??
    null;
  return { speciesVi: MUSHROOM_SUBSPECIES_VI[slug], conf, abstained: false, safetyNoteVi: null };
}

function itemDisplayName(item: Item, det?: Detection): string {
  const info = resolveMushroomSubspecies(item, det);
  if (info.abstained) return 'Nấm';
  if (info.speciesVi && item.ingredient_name_vi.trim().toLowerCase() === 'nấm') {
    return info.speciesVi;
  }
  return item.ingredient_name_vi;
}

function worstCaseDetectionIndex(detections: Detection[]): number {
  if (detections.length <= 1) return 0;
  let bestIdx = 0;
  let bestScore = -1;
  detections.forEach((d, idx) => {
    const score = (d.p_kiem_tra ?? 0) * 1000 + (d.p_dung_ngay ?? 0) * 100 + (d.p_dung_som ?? 0) * 10 - (d.p_tuoi ?? 0);
    if (score > bestScore) {
      bestScore = score;
      bestIdx = idx;
    }
  });
  return bestIdx;
}

/** Xác nhận nguyên liệu (UC13): authenticated blob image + SVG bboxes + calibrated freshness probabilities + confirm. */
export default function ConfirmScan() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { c } = useTheme();
  const { isDesktop: desktop } = useLayout();
  const ref = useReference();
  const catalog = useCatalog();
  const lots = useLots();
  const [editing, setEditing] = useState<{ item: Item; detectionId?: number } | null>(null);
  const [adding, setAdding] = useState(false);
  const [result, setResult] = useState<Schemas['ScanConfirmResult'] | null>(null);
  const [activeOrdinal, setActiveOrdinal] = useState<number>(1);
  const [imageOpen, setImageOpen] = useState(true);

  const scan = useQuery({
    queryKey: ['scan', id],
    queryFn: ({ signal }) => call(api.GET('/scans/{id}', { params: { path: { id }, query: { wait: 10 } }, signal })),
    refetchInterval: (q) => (q.state.data && ['queued', 'processing'].includes(q.state.data.status) ? 500 : false),
  });
  const reload = () => scan.refetch();

  const confirm = useMutation({
    mutationFn: () =>
      call(
        api.POST('/scans/{id}/confirm', {
          params: { path: { id } },
          body: {},
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

  const s = scan.data;
  const activeImg = s?.images?.find((im) => im.ordinal === activeOrdinal) ?? s?.images?.[0] ?? null;

  const scanStatus = s?.status;
  const imgOrdinal = activeImg?.ordinal;
  const imgPurged = activeImg?.purged;
  const imgKey = scanStatus === 'done' && imgOrdinal != null && !imgPurged ? `${id}:${imgOrdinal}` : null;
  const [imgResult, setImgResult] = useState<{ key: string; status: 'ready' | 'purged' | 'error'; uri: string | null } | null>(null);

  useEffect(() => {
    if (!imgKey || imgOrdinal == null) return;
    let alive = true;
    let objectUrl: string | null = null;
    const ac = new AbortController();

    (async () => {
      try {
        const res = await api.GET('/scans/{id}/images/{ordinal}', {
          params: { path: { id, ordinal: imgOrdinal } },
          parseAs: 'blob',
          signal: ac.signal,
        });
        if (!alive) return;
        if (res.response.status === 410 || res.response.status === 404) {
          setImgResult({ key: imgKey, status: 'purged', uri: null });
          return;
        }
        if (!res.response.ok || !res.data) {
          setImgResult({ key: imgKey, status: 'error', uri: null });
          return;
        }
        const blob = res.data as Blob;
        if (Platform.OS === 'web') {
          objectUrl = URL.createObjectURL(blob);
          setImgResult({ key: imgKey, status: 'ready', uri: objectUrl });
        } else {
          const reader = new FileReader();
          reader.onloadend = () => {
            if (!alive) return;
            const dataUri = typeof reader.result === 'string' ? reader.result : null;
            setImgResult(dataUri ? { key: imgKey, status: 'ready', uri: dataUri } : { key: imgKey, status: 'error', uri: null });
          };
          reader.onerror = () => {
            if (alive) setImgResult({ key: imgKey, status: 'error', uri: null });
          };
          reader.readAsDataURL(blob);
        }
      } catch {
        if (alive) setImgResult({ key: imgKey, status: 'error', uri: null });
      }
    })();

    return () => {
      alive = false;
      ac.abort();
      if (objectUrl && Platform.OS === 'web') {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [id, imgKey, imgOrdinal]);

  const imgState: { status: 'idle' | 'loading' | 'ready' | 'purged' | 'error'; uri: string | null } = imgPurged
    ? { status: 'purged', uri: null }
    : !imgKey
      ? { status: 'idle', uri: null }
      : imgResult?.key === imgKey
        ? { status: imgResult.status, uri: imgResult.uri }
        : { status: 'loading', uri: null };

  if (scan.isLoading) {
    return (
      <Screen>
        <Loading label="Đang tải kết quả quét…" />
      </Screen>
    );
  }
  if (scan.error || !s) {
    return (
      <Screen>
        <ErrorBox message={errorText(scan.error)} onRetry={reload} />
      </Screen>
    );
  }

  if (s.status === 'queued' || s.status === 'processing') {
    return (
      <Screen testID="screen-scan-wait" variant="focused">
        <T v="h1" accessibilityRole="header">
          Đang xử lý ảnh quét
        </T>
        <Loading label={s.status === 'queued' ? 'Ảnh đang chờ xử lý…' : 'Đang nhận diện nguyên liệu…'} />
      </Screen>
    );
  }
  if (s.status === 'failed' || s.status === 'expired') {
    return (
      <Screen variant="focused">
        <T v="h1" accessibilityRole="header">
          Kết quả quét
        </T>
        <Notice tone="warn">
          <T v="title">Không nhận diện được</T>
          <T>{s.error_code ? codeText(s.error_code) : 'Ảnh chưa xử lý được.'}</T>
        </Notice>
        <Button label="Quét lại" onPress={() => router.replace({ pathname: '/quet', params: { mode: s.mode } })} />
        <Button label="Nhập tay vào Tủ lạnh" kind="secondary" onPress={() => goTab('/kho')} />
      </Screen>
    );
  }
  if (s.status === 'discarded') {
    return (
      <Screen testID="screen-scan-discarded" variant="focused">
        <T v="h1" accessibilityRole="header">
          Đã bỏ lần quét này
        </T>
        <Notice>
          <T>Kết quả quét này đã được bỏ và không thêm vào tủ lạnh.</T>
        </Notice>
        <Button label="Quét lại" onPress={() => router.replace({ pathname: '/quet', params: { mode: s.mode } })} />
        <Button label="Mở Tủ lạnh" kind="secondary" onPress={() => goTab('/kho')} />
      </Screen>
    );
  }
  if (result || s.status === 'confirmed') {
    return (
      <Screen testID="screen-scan-done" variant="focused">
        <T v="h1" accessibilityRole="header">
          Đã lưu vào Tủ lạnh
        </T>
        <Notice tone="ok">
          <T v="title">Đã lưu xong</T>
          {result ? (
            <T tabular>
              Đã thêm {result.created_lot_ids.length} nguyên liệu mới
              {result.not_seen_lot_ids.length ? `, ${result.not_seen_lot_ids.length} nguyên liệu chưa thấy lần này (xem lại ở Tủ lạnh)` : ''}.
            </T>
          ) : null}
        </Notice>
        <Button label="Xem gợi ý nấu ăn" onPress={() => goTab('/mam')} />
        <Button label="Mở Tủ lạnh" kind="secondary" onPress={() => goTab('/kho')} />
      </Screen>
    );
  }

  const live = s.items.filter((i) => i.user_action !== 'deleted') as Item[];
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

  const detectionsOnActiveImg = activeImg
    ? live.flatMap((item) =>
        item.detections
          .filter((d) => d.image_ordinal === activeImg.ordinal)
          .map((d, idx) => ({ item, d, idx })),
      )
    : [];

  const chip = (i: Item) => {
    const ing = catalog.ingredients.get(i.ingredient_id);
    const countable = ing ? ing.countable && Boolean(ing.units?.length) : i.final_count != null;
    const conf = Math.max(0, ...i.detections.map((d) => d.confidence));
    const low = i.origin === 'model' && conf > 0 && conf < 0.5;
    const qty = i.final_count ?? i.model_count;
    const unitCode = ing?.units?.[0]?.unit_code;
    const unitName = unitCode ? (UNIT_LABEL[unitCode] ?? unitCode) : 'cái';
    const qtyText = countable
      ? qty
        ? `, ${qty} ${unitName}`
        : ''
      : i.qty_level
        ? `, ${LEVEL_LABEL[i.qty_level].toLowerCase()}`
        : ', chưa rõ lượng';
    return (
      <View key={i.id} style={{ opacity: low ? 0.75 : 1, maxWidth: '100%', flexShrink: 1 }}>
        <Chip
          testID={`scan-chip-${i.ingredient_name_vi}`}
          onPress={() => setEditing({ item: i })}
          label={`${itemDisplayName(i)}${qtyText}${low ? ', cần xem lại' : ''}`}
          left={<FreshBadge value={fresh(i)} small />}
        />
      </View>
    );
  };

  const imagePane = (
    <Card testID="scan-image-pane" variant="ledger" style={{ gap: space.md }}>
      <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
        <T v="h2" accessibilityRole="header">
          Ảnh quét &amp; vùng nhận diện
        </T>
        {!desktop ? (
          <Button
            kind="ghost"
            label={imageOpen ? 'Thu gọn ảnh' : 'Xem ảnh'}
            onPress={() => setImageOpen((v) => !v)}
            style={{ paddingHorizontal: space.sm }}
          />
        ) : null}
      </Row>

      {(desktop || imageOpen) && s.images.length > 0 ? (
        <>
          {s.images.length > 1 ? (
            <Row gap={space.sm}>
              {s.images.map((im) => (
                <Chip
                  key={im.ordinal}
                  label={`Ảnh ${im.ordinal}`}
                  selected={(activeImg?.ordinal ?? 1) === im.ordinal}
                  onPress={() => setActiveOrdinal(im.ordinal)}
                />
              ))}
            </Row>
          ) : null}

          {imgState.status === 'loading' ? <Loading label="Đang tải ảnh…" rows={1} /> : null}
          {imgState.status === 'purged' ? (
            <View style={{ backgroundColor: c.surfaceAlt, borderWidth: 1, borderColor: c.hairline, borderRadius: radius.sm, padding: space.md }}>
              <T>Ảnh gốc đã được xoá sau 30 ngày theo chính sách lưu trữ. Bạn vẫn có thể sửa và xác nhận nguyên liệu bên dưới.</T>
            </View>
          ) : null}
          {imgState.status === 'error' ? (
            <View style={{ backgroundColor: c.warnSoft, borderWidth: 1, borderColor: c.hairline, borderRadius: radius.sm, padding: space.md }}>
              <T>Không tải được ảnh gốc, bạn vẫn sửa và xác nhận được danh sách nguyên liệu.</T>
            </View>
          ) : null}
          {imgState.status === 'ready' && imgState.uri && activeImg ? (
            <View
              style={{
                width: '100%',
                aspectRatio: activeImg.width > 0 && activeImg.height > 0 ? activeImg.width / activeImg.height : 4 / 3,
                borderRadius: radius.md,
                overflow: 'hidden',
                backgroundColor: c.surfaceAlt,
                position: 'relative',
              }}>
              <Image
                source={{ uri: imgState.uri }}
                style={{ width: '100%', height: '100%' }}
                contentFit="fill"
                accessibilityLabel={`Ảnh quét ${activeImg.ordinal}`}
              />
              {detectionsOnActiveImg.length > 0 ? (
                <View style={StyleSheet.absoluteFill} testID="scan-bbox-overlay">
                  {detectionsOnActiveImg.map(({ item, d }, pos) => {
                    const selected = editing?.detectionId === d.id || editing?.item.id === item.id;
                    const uncertain = d.confidence < 0.5;
                    const boxColor = selected ? c.accent : uncertain ? c.fresh.dung_som : c.lime;
                    const badgeTone = selected || uncertain ? 'onAccent' : 'onLime';
                    const leftPct = Math.max(0, Math.min(100, d.x1 * 100));
                    const topPct = Math.max(0, Math.min(100, d.y1 * 100));
                    const widthPct = Math.max(1, Math.min(100 - leftPct, (d.x2 - d.x1) * 100));
                    const heightPct = Math.max(1, Math.min(100 - topPct, (d.y2 - d.y1) * 100));
                    const pct = (v: number) => `${Number(v.toFixed(4))}%` as `${number}%`;
                    return (
                      <Pressable
                        key={d.id}
                        testID={`scan-bbox-${pos + 1}`}
                        accessibilityRole="button"
                        accessibilityLabel={`Vùng #${pos + 1} ${itemDisplayName(item, d)} (${Math.round(d.confidence * 100)}%)`}
                        onPress={() => setEditing({ item, detectionId: d.id })}
                        style={{
                          position: 'absolute',
                          left: pct(leftPct),
                          top: pct(topPct),
                          width: pct(widthPct),
                          height: pct(heightPct),
                          borderWidth: selected ? 3 : 2,
                          borderColor: boxColor,
                          borderRadius: 4,
                        }}>
                        <View
                          pointerEvents="none"
                          style={[
                            StyleSheet.absoluteFill,
                            {
                              backgroundColor: boxColor,
                              opacity: selected ? 0.14 : uncertain ? 0.12 : 0.1,
                            },
                          ]}
                        />
                        <View
                          style={{
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            paddingHorizontal: 5,
                            paddingVertical: 1,
                            borderBottomRightRadius: 4,
                            backgroundColor: boxColor,
                          }}>
                          <T tone={badgeTone} tabular style={{ fontSize: size.xs, lineHeight: 16, fontWeight: '700' }}>
                            #{pos + 1}
                          </T>
                        </View>
                      </Pressable>
                    );
                  })}
                </View>
              ) : null}
            </View>
          ) : null}

          {detectionsOnActiveImg.length > 0 ? (
            <View style={{ gap: space.xs }}>
              <T v="small" tone="muted">
                Chạm khung hoặc thẻ bên dưới để xem xác suất độ tươi:
              </T>
              <Row gap={space.sm}>
                {detectionsOnActiveImg.map(({ item, d }, pos) => {
                  const uncertain = d.confidence < 0.5;
                  const label = itemDisplayName(item, d);
                  return (
                    <Pressable
                      key={d.id}
                      accessibilityRole="button"
                      accessibilityLabel={`Xem vùng ${label} (${Math.round(d.confidence * 100)}%)`}
                      onPress={() => setEditing({ item, detectionId: d.id })}
                      style={{
                        minHeight: TOUCH,
                        maxWidth: '100%',
                        flexShrink: 1,
                        paddingHorizontal: space.md,
                        paddingVertical: space.xs,
                        borderRadius: radius.sm,
                        backgroundColor: uncertain ? c.fresh.dung_som : c.lime,
                        justifyContent: 'center',
                      }}>
                      <T v="small" tone={uncertain ? 'onAccent' : 'onLime'} tabular style={{ fontWeight: '600', flexShrink: 1 }}>
                        #{pos + 1} {label}, {Math.round(d.confidence * 100)}%
                      </T>
                    </Pressable>
                  );
                })}
              </Row>
            </View>
          ) : null}
        </>
      ) : null}
    </Card>
  );

  const abstainedMushroomItem = live.find((i) => resolveMushroomSubspecies(i).abstained);
  const abstainedMushroomNote = abstainedMushroomItem ? resolveMushroomSubspecies(abstainedMushroomItem).safetyNoteVi : null;
  const hasAbstainedMushroom = Boolean(abstainedMushroomItem);

  const chipsPane = (
    <View style={{ gap: space.lg, flex: 1, minWidth: 0 }}>
      {abstainedMushroomNote ? (
        <Notice tone="warn" testID="mushroom-safety-banner">
          <T v="label" tone="warn">
            Cần xác nhận hoặc loại bỏ nấm chưa rõ loại trước khi đưa vào kho
          </T>
          <T v="small" tone="warn" style={{ fontWeight: '600' }}>
            {abstainedMushroomNote}
          </T>
          <T v="small" tone="muted">
            Chạm vào thẻ Nấm bên dưới để đổi sang đúng loại nấm mua tại chợ hoặc siêu thị, hoặc xoá nếu không chắc chắn.
          </T>
        </Notice>
      ) : null}
      {check.length ? (
        <Section title="Cần kiểm tra trước khi dùng">
          <T v="small" tone="muted">
            Xem, ngửi thử rồi chọn độ tươi. Hệ thống sẽ không gợi ý nấu món cần nguyên liệu này cho tới khi bạn xác nhận.
          </T>
          <Row>{check.map(chip)}</Row>
        </Section>
      ) : null}
      {[...groups.entries()].map(([g, list]) => (
        <Section key={g} title={g}>
          <Row>{list.map(chip)}</Row>
        </Section>
      ))}
      {!live.length ? (
        <Notice tone="info">
          <T>Chưa nhận diện được nguyên liệu nào trong ảnh. Bạn có thể tự thêm nguyên liệu bị sót.</T>
        </Notice>
      ) : null}
      <T v="small" tone="muted">
        Hệ thống tự nhận diện rau củ, thịt, cá, trứng, nấm và đồ đóng gói. Món nào thiếu bạn bấm thêm tay ngay bên dưới.
      </T>
      <Button label="+ Thêm nguyên liệu bị sót" kind="secondary" onPress={() => setAdding(true)} />
      {unseen.length ? (
        <Section title="Chưa thấy trong lần kiểm kê này">
          <T v="small" tone="muted">
            Các món này đang có trong tủ nhưng không thấy trong ảnh; bạn có thể xác nhận lại ở Tủ lạnh.
          </T>
          <T>{unseen.map((l) => l.ingredient_name_vi).join(', ')}</T>
        </Section>
      ) : null}
    </View>
  );

  return (
    <Screen
      testID="screen-scan-confirm"
      footer={
        <>
          {confirm.error ? <ErrorBox message={errorText(confirm.error)} /> : null}
          <Button
            label="Lưu vào Tủ lạnh"
            testID="scan-confirm"
            onPress={() => confirm.mutate()}
            loading={confirm.isPending}
            disabled={hasAbstainedMushroom || confirm.isPending}
          />
          <Button label="Bỏ kết quả này" kind="ghost" onPress={() => discard.mutate()} loading={discard.isPending} />
        </>
      }>
      <View style={{ gap: space.xs }}>
        <T v="h1" accessibilityRole="header">
          Xác nhận nguyên liệu
        </T>
        <T tone="muted">Chạm vào một nguyên liệu để sửa tên, số lượng hoặc độ tươi.</T>
      </View>

      {desktop ? (
        <View style={{ flexDirection: 'row', gap: space.xl, alignItems: 'flex-start' }}>
          <View style={{ flex: 5, minWidth: 0 }}>{imagePane}</View>
          <View style={{ flex: 7, minWidth: 0 }}>{chipsPane}</View>
        </View>
      ) : (
        <>
          {imagePane}
          {chipsPane}
        </>
      )}

      {editing ? (
        <EditChip
          scanId={id}
          classifierVersionId={s.classifier_version_id}
          item={editing.item}
          initialDetectionId={editing.detectionId}
          onClose={() => setEditing(null)}
          reload={reload}
        />
      ) : null}
      <AddChip scanId={id} visible={adding} onClose={() => setAdding(false)} reload={reload} />
    </Screen>
  );
}

function EditChip({
  scanId,
  classifierVersionId,
  item,
  initialDetectionId,
  onClose,
  reload,
}: {
  scanId: string;
  classifierVersionId: string | null;
  item: Item;
  initialDetectionId?: number;
  onClose: () => void;
  reload: () => void;
}) {
  const { c } = useTheme();
  const catalog = useCatalog();
  const ing = catalog.ingredients.get(item.ingredient_id);
  const [count, setCount] = useState(item.final_count ?? item.model_count ?? 1);
  const [level, setLevel] = useState(item.qty_level);
  const [freshness, setFreshness] = useState<Exclude<Freshness, 'chua_ro'> | null>(item.user_freshness ?? null);
  const [relabel, setRelabel] = useState<Schemas['Ingredient'] | null>(null);
  const [detIdx, setDetIdx] = useState(() => {
    if (initialDetectionId != null) {
      const idx = item.detections.findIndex((d) => d.id === initialDetectionId);
      if (idx >= 0) return idx;
    }
    return worstCaseDetectionIndex(item.detections);
  });

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
  const countable = relabel
    ? relabel.countable && Boolean(relabel.units?.length)
    : ing
      ? ing.countable && Boolean(ing.units?.length)
      : item.final_count != null;
  const save = () =>
    patch.mutate({
      ...(relabel ? { ingredient_id: relabel.id } : {}),
      ...(countable ? { final_count: count } : { qty_level: level }),
      ...(freshness ? { user_freshness: freshness } : {}),
    });

  const activeDet = item.detections[detIdx] ?? item.detections[0];
  const mushroomInfo = resolveMushroomSubspecies(item, activeDet);
  const sheetTitle = itemDisplayName(item, activeDet);
  const hasProbs =
    activeDet != null &&
    (activeDet.p_tuoi != null || activeDet.p_dung_som != null || activeDet.p_dung_ngay != null || activeDet.p_kiem_tra != null);

  const probRows: { key: Exclude<Freshness, 'chua_ro'>; label: string; prob: number | null | undefined; color: string }[] = activeDet
    ? [
        { key: 'tuoi', label: 'Tươi', prob: activeDet.p_tuoi, color: c.fresh.tuoi },
        { key: 'dung_som', label: 'Nên dùng sớm', prob: activeDet.p_dung_som, color: c.fresh.dung_som },
        { key: 'dung_ngay', label: 'Dùng ngay', prob: activeDet.p_dung_ngay, color: c.fresh.dung_ngay },
        { key: 'kiem_tra', label: 'Cần kiểm tra', prob: activeDet.p_kiem_tra, color: c.fresh.kiem_tra },
      ]
    : [];

  return (
    <Sheet visible onClose={onClose} title={sheetTitle} testID="sheet-scan-item">
      {mushroomInfo.speciesVi ? (
        <View
          testID="mushroom-subspecies-badge"
          style={{ backgroundColor: c.herbSoft, borderRadius: radius.md, paddingHorizontal: space.md, paddingVertical: space.sm }}>
          <T v="small" tone="herb" tabular style={{ fontWeight: '600' }}>
            Loại nấm nhận diện: {mushroomInfo.speciesVi}
            {mushroomInfo.conf != null ? ` (${Math.round(mushroomInfo.conf * 100)}%)` : ''}
          </T>
        </View>
      ) : mushroomInfo.abstained && mushroomInfo.safetyNoteVi ? (
        <View
          testID="mushroom-safety-note"
          style={{ backgroundColor: c.warnSoft, borderRadius: radius.md, paddingHorizontal: space.md, paddingVertical: space.sm }}>
          <T v="small" tone="warn" style={{ fontWeight: '600' }}>
            {mushroomInfo.safetyNoteVi}
          </T>
        </View>
      ) : null}
      <View testID="freshness-prob-bars" style={{ gap: space.sm }}>
        <T v="label">Đánh giá độ tươi tự động</T>
        {item.origin === 'user_added' || item.detections.length === 0 ? (
          <Notice tone="info">
            <T v="small">Nguyên liệu do bạn tự thêm, chọn độ tươi thủ công.</T>
          </Notice>
        ) : classifierVersionId == null || !hasProbs ? (
          <Notice tone="warn">
            <T v="small">Chưa có điểm độ tươi tự động, hãy tự kiểm tra.</T>
          </Notice>
        ) : (
          <Card style={{ gap: space.sm, backgroundColor: c.surfaceAlt }}>
            {item.detections.length > 1 ? (
              <Row gap={space.sm}>
                {item.detections.map((d, idx) => (
                  <Chip
                    key={d.id}
                    label={`Phát hiện #${idx + 1}`}
                    selected={detIdx === idx}
                    onPress={() => setDetIdx(idx)}
                  />
                ))}
              </Row>
            ) : null}
            {probRows.map((row) => {
              const pct = Math.round((row.prob ?? 0) * 100);
              return (
                <View key={row.key} style={{ gap: 4 }} accessibilityLabel={`Xác suất ${row.label} ${pct}%`}>
                  <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                    <T v="small">{row.label}</T>
                    <T v="small" tabular style={{ fontWeight: '600' }}>
                      {pct}%
                    </T>
                  </Row>
                  <View style={{ height: 8, borderRadius: radius.sm, backgroundColor: c.surface, overflow: 'hidden' }}>
                    <View style={{ width: `${Math.min(100, Math.max(0, pct))}%`, height: 8, borderRadius: radius.sm, backgroundColor: row.color }} />
                  </View>
                </View>
              );
            })}
          </Card>
        )}
      </View>

      <Section title="Đổi tên (nếu nhận sai)">
        <IngredientSearch onPick={setRelabel} picked={relabel} />
      </Section>
      {countable ? (
        <Stepper label="Số lượng" value={count} onChange={setCount} min={0} max={99} />
      ) : (
        <Segmented label="Lượng" options={LEVELS} value={level} onChange={setLevel} />
      )}
      <Segmented
        label="Độ tươi"
        column={space.xs}
        options={(['tuoi', 'dung_som', 'dung_ngay', 'kiem_tra'] as const).map((f) => [f, FRESH_LABEL[f]] as const)}
        value={freshness}
        onChange={setFreshness}
      />
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
          <Segmented options={LEVELS} value={level} onChange={setLevel} />
        )
      ) : null}
      {add.error ? <ErrorBox message={errorText(add.error)} /> : null}
      <Button label="Thêm" onPress={() => add.mutate()} disabled={!ing} loading={add.isPending} />
    </Sheet>
  );
}
