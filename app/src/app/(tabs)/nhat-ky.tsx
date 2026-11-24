import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigation, useRouter } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { AppState, Pressable, View } from 'react-native';

import { api, call } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { Icon, SLOT_LABEL } from '@/components/domain';
import { MacroPieLedger } from '@/components/MacroPieLedger';
import { Button, Card, Empty, ErrorBox, Loading, Notice, Row, Screen, Section, T } from '@/components/ui';
import { hamiltonMacroShares } from '@/lib/caloriePlate';
import {
  localDateString,
  MEAL_SLOT_LABEL,
  mealLogOutToEntry,
  type QuickMealLogEntry,
  removeQuickMealLog,
  useQuickMealLogs,
} from '@/lib/mealLog';
import { goTab } from '@/lib/nav';
import { MEAL_LABEL, qk, useProfile } from '@/lib/queries';
import { font, radius, space, TOUCH, useLayout, useTheme } from '@/theme';

function isoWeek(d: Date): string {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y = t.getUTCFullYear();
  const w = Math.ceil(((t.getTime() - Date.UTC(y, 0, 1)) / 86400000 + 1) / 7);
  return `${y}-W${String(w).padStart(2, '0')}`;
}

const WD = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];

/** Nhật ký tuần (UC22): today macro/calorie budget + cooked trays + quick-logged scans + weekly summary. */
export default function Journal() {
  const { c } = useTheme();
  const { status, user } = useSession();
  const qc = useQueryClient();
  const router = useRouter();
  const nav = useNavigation() as { addListener?: (ev: string, cb: () => void) => () => void };
  const { isDesktop, isMobile } = useLayout();
  const [offset, setOffset] = useState(0);
  const [nowTs, setNowTs] = useState(() => Date.now());
  const week = isoWeek(new Date(nowTs + offset * 7 * 86400000));

  useEffect(() => {
    const refreshNow = () => {
      setNowTs(Date.now());
    };
    const unsub = typeof nav?.addListener === 'function' ? nav.addListener('focus', refreshNow) : undefined;
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active') refreshNow();
    });
    return () => {
      unsub?.();
      sub.remove();
    };
  }, [nav]);

  const q = useQuery({
    queryKey: qk.journal(week),
    queryFn: () => call(api.GET('/journal', { params: { query: { week } } })),
    enabled: status === 'signedIn',
  });
  const quickLogsQ = useQuickMealLogs(week);
  const profile = useProfile();

  const serverLogs = useMemo(() => (q.data?.meal_logs ?? []).map(mealLogOutToEntry), [q.data?.meal_logs]);
  const serverIncludedIds = useMemo(() => new Set(serverLogs.map((m) => m.id)), [serverLogs]);

  const quickEntries = useMemo(() => {
    const map = new Map<string, QuickMealLogEntry>();
    for (const e of [...(quickLogsQ.data ?? []), ...serverLogs]) {
      if (!map.has(e.id)) map.set(e.id, e);
    }
    return [...map.values()].sort((a, b) => (b.logged_at || '').localeCompare(a.logged_at || ''));
  }, [quickLogsQ.data, serverLogs]);

  // Only entries not already aggregated by GET /journal (e.g., pending offline creations) are added on top.
  const uncountedQuick = useMemo(
    () => quickEntries.filter((e) => !serverIncludedIds.has(e.id)),
    [quickEntries, serverIncludedIds],
  );

  const uncountedByDate = useMemo(() => {
    const map = new Map<string, QuickMealLogEntry[]>();
    for (const entry of uncountedQuick) {
      const prev = map.get(entry.date) ?? [];
      prev.push(entry);
      map.set(entry.date, prev);
    }
    return map;
  }, [uncountedQuick]);

  const allQuickByDate = useMemo(() => {
    const map = new Map<string, QuickMealLogEntry[]>();
    for (const entry of quickEntries) {
      const prev = map.get(entry.date) ?? [];
      prev.push(entry);
      map.set(entry.date, prev);
    }
    return map;
  }, [quickEntries]);

  const days = useMemo(() => q.data?.days ?? [], [q.data?.days]);
  const dayKcalTotals = useMemo(
    () =>
      days.map((d) => {
        const extraList = uncountedByDate.get(d.date) ?? [];
        const extraKcal = extraList.reduce((s, e) => s + e.kcal, 0);
        const totalAllLogsForDay = (allQuickByDate.get(d.date) ?? []).length;
        const quickCount = d.meal_logs_count != null ? Math.max(d.meal_logs_count, totalAllLogsForDay) : totalAllLogsForDay;
        const hasAny = d.kcal_per_person != null || extraList.length > 0;
        const total = hasAny ? (d.kcal_per_person ?? 0) + extraKcal : null;
        return { ...d, totalKcal: total, quickCount };
      }),
    [days, uncountedByDate, allQuickByDate],
  );

  const max = Math.max(1, ...dayKcalTotals.map((d) => Math.max(d.totalKcal ?? 0, d.e_target_kcal ?? 0)));
  const trays = days.reduce((s, d) => s + d.cooked_trays, 0);
  const urgent = days.reduce((s, d) => s + d.urgent_lots_used, 0);
  const macros = q.data?.macros;
  const history = q.data?.cooked_history ?? [];

  const uncountedMacroSums = useMemo(
    () =>
      uncountedQuick.reduce(
        (acc, e) => ({
          protein_g: acc.protein_g + e.protein_g,
          carbs_g: acc.carbs_g + e.carbs_g,
          fat_g: acc.fat_g + e.fat_g,
          fiber_g: acc.fiber_g + e.fiber_g,
        }),
        { protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 },
      ),
    [uncountedQuick],
  );

  const wkProteinG = (macros?.protein_g ?? 0) + uncountedMacroSums.protein_g;
  const wkCarbsG = (macros?.carbs_g ?? 0) + uncountedMacroSums.carbs_g;
  const wkFatG = (macros?.fat_g ?? 0) + uncountedMacroSums.fat_g;
  const wkFiberG = (macros?.fiber_g ?? 0) + uncountedMacroSums.fiber_g;
  const wkEnergySplit = hamiltonMacroShares(wkProteinG * 4, wkCarbsG * 4, wkFatG * 9);

  const hasWeeklyMacros = Boolean(macros || quickEntries.length > 0);
  const macroRows = hasWeeklyMacros
    ? [
        { key: 'protein', label: 'Đạm', grams: wkProteinG, pct: wkEnergySplit.protein_pct, color: c.macro.protein },
        { key: 'carb', label: 'Tinh bột', grams: wkCarbsG, pct: wkEnergySplit.carbs_pct, color: c.macro.carb },
        { key: 'fat', label: 'Chất béo', grams: wkFatG, pct: wkEnergySplit.fat_pct, color: c.macro.fat },
      ]
    : [];

  const sampleTarget = days.find((d) => d.e_target_kcal != null)?.e_target_kcal ?? profile.data?.kcal_target ?? null;

  const todayStr = localDateString(new Date(nowTs));
  const todayDay = dayKcalTotals.find((d) => d.date === todayStr);
  const todayUncounted = uncountedByDate.get(todayStr) ?? [];
  const todayUncountedKcal = todayUncounted.reduce((s, e) => s + e.kcal, 0);
  const todayTotalKcal = Math.round((todayDay?.totalKcal ?? todayUncountedKcal) || 0);
  const todayTarget = todayDay?.e_target_kcal ?? sampleTarget;
  const todayPct = todayTarget && todayTarget > 0 ? Math.min(100, Math.round((todayTotalKcal / todayTarget) * 100)) : 0;
  const todayDiff = todayTarget != null ? Math.round(todayTarget - todayTotalKcal) : null;
  const todayUncountedMacros = todayUncounted.reduce(
    (acc, e) => ({
      protein_g: Math.round((acc.protein_g + e.protein_g) * 10) / 10,
      carbs_g: Math.round((acc.carbs_g + e.carbs_g) * 10) / 10,
      fat_g: Math.round((acc.fat_g + e.fat_g) * 10) / 10,
      fiber_g: Math.round((acc.fiber_g + e.fiber_g) * 10) / 10,
    }),
    { protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 },
  );

  const todayHistory = history.filter((m) => m.date === todayStr);
  const todayCookedMacros = todayHistory.reduce(
    (acc, m) => ({
      protein_g: acc.protein_g + (m.macros?.protein_g ?? 0),
      carbs_g: acc.carbs_g + (m.macros?.carbs_g ?? 0),
      fat_g: acc.fat_g + (m.macros?.fat_g ?? 0),
      fiber_g: acc.fiber_g + (m.macros?.fiber_g ?? 0),
    }),
    { protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 },
  );
  const dayObj = todayDay as (typeof todayDay & { protein_g?: number | null; carbs_g?: number | null; fat_g?: number | null; fiber_g?: number | null }) | undefined;
  const cookedP = dayObj?.protein_g ?? todayCookedMacros.protein_g;
  const cookedC = dayObj?.carbs_g ?? todayCookedMacros.carbs_g;
  const cookedF = dayObj?.fat_g ?? todayCookedMacros.fat_g;
  const cookedFiber = dayObj?.fiber_g ?? todayCookedMacros.fiber_g;
  const hasTodayCookedMacros = cookedP + cookedC + cookedF + cookedFiber > 0;

  const todayCombinedMacros = {
    protein_g: Math.round((todayUncountedMacros.protein_g + cookedP) * 10) / 10,
    carbs_g: Math.round((todayUncountedMacros.carbs_g + cookedC) * 10) / 10,
    fat_g: Math.round((todayUncountedMacros.fat_g + cookedF) * 10) / 10,
    fiber_g: Math.round((todayUncountedMacros.fiber_g + cookedFiber) * 10) / 10,
  };
  const showTodayMacroLedger = (allQuickByDate.get(todayStr)?.length ?? 0) > 0 || hasTodayCookedMacros || todayTotalKcal === 0;

  const handleDeleteQuickLog = async (entryId: string) => {
    await removeQuickMealLog(entryId, user?.id);
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['quick-logs'] }),
      qc.invalidateQueries({ queryKey: ['journal'] }),
    ]);
  };

  const showContent = Boolean(q.data || quickEntries.length > 0);

  const leftCol = showContent ? (
    <View style={{ gap: space.lg }}>
      {offset === 0 ? (
        <Card testID="journal-today-summary" variant="ledger" style={{ gap: space.md }}>
          <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'nowrap' }} gap={space.sm}>
            <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
              <T v="label" tone="accent">
                Hôm nay
              </T>
              <T v="h2" accessibilityRole="header">
                Năng lượng &amp; đa lượng trong ngày
              </T>
            </View>
            <T v={isMobile ? 'h1' : 'huge'} tabular tone="accent" style={{ flexShrink: 0 }}>
              {todayTotalKcal} kcal
            </T>
          </Row>

          {todayTarget != null ? (
            <View style={{ gap: 6 }}>
              <View style={{ height: 8, borderRadius: radius.sm, backgroundColor: c.surfaceAlt, overflow: 'hidden' }}>
                <View
                  style={{
                    width: `${todayPct}%`,
                    height: 8,
                    borderRadius: radius.sm,
                    backgroundColor: todayDiff != null && todayDiff < -todayTarget * 0.1 ? c.warn : c.herb,
                  }}
                />
              </View>
              <Row style={{ justifyContent: 'space-between' }}>
                <T v="small" tone="muted" tabular>
                  Mục tiêu: {Math.round(todayTarget)} kcal ({todayPct}%)
                </T>
                <T v="small" tone={todayDiff != null && todayDiff >= 0 ? 'herb' : 'warn'} tabular>
                  {todayDiff != null
                    ? todayDiff >= 0
                      ? `Còn lại ${todayDiff} kcal`
                      : `Vượt ${Math.abs(todayDiff)} kcal`
                    : ''}
                </T>
              </Row>
            </View>
          ) : (
            <T v="small" tone="muted">
              Đặt mục tiêu năng lượng trong Cài đặt để theo dõi phần còn lại mỗi ngày.
            </T>
          )}

          {showTodayMacroLedger ? (
            <MacroPieLedger
              title="Tổng hợp đa lượng hôm nay"
              proteinG={todayCombinedMacros.protein_g}
              carbsG={todayCombinedMacros.carbs_g}
              fatG={todayCombinedMacros.fat_g}
              fiberG={todayCombinedMacros.fiber_g}
              totalKcal={todayTotalKcal}
              massG={null}
              context="daily"
            />
          ) : (
            <View testID="journal-today-macro-note" style={{ backgroundColor: c.surfaceAlt, borderRadius: radius.sm, padding: space.md }}>
              <T v="small" tone="muted">
                Chỉ số đa lượng chi tiết hiển thị cho các bữa ghi nhanh từ mục Quét món.
              </T>
            </View>
          )}
        </Card>
      ) : null}

      <View
        style={{
          flexDirection: 'row',
          borderWidth: 1.5,
          borderColor: c.border,
          borderRadius: radius.md,
          backgroundColor: c.surface,
          overflow: 'hidden',
        }}>
        <View style={{ flex: 1, minWidth: 96, padding: space.md }}>
          <T v="huge" tabular tone="accent">
            {trays}
          </T>
          <T v="small" tone="muted">mâm đã nấu</T>
        </View>
        <View style={{ flex: 1, minWidth: 96, padding: space.md, borderLeftWidth: 1, borderLeftColor: c.hairline }}>
          <T v="huge" tabular tone="info">
            {quickEntries.length}
          </T>
          <T v="small" tone="muted">bữa quét nhanh</T>
        </View>
        <View style={{ flex: 1, minWidth: 96, padding: space.md, borderLeftWidth: 1, borderLeftColor: c.hairline }}>
          <T v="huge" tabular tone="herb">
            {urgent}
          </T>
          <T v="small" tone="muted">lô dùng kịp</T>
        </View>
      </View>

      {q.data?.kcal_range_status === 'calibrating' ? (
        <Notice>
          <T>Số calo đang hiệu chỉnh: chưa đủ món đối chiếu với Viện Dinh dưỡng Quốc gia nên chỉ xem như số tham khảo.</T>
        </Notice>
      ) : null}

      {trays === 0 && history.length === 0 && quickEntries.length === 0 ? (
        <Empty
          title="Tuần này bạn chưa ghi nhận bữa nào"
          body="Ghép mâm và nấu một bữa, hoặc quét nhanh món ăn ở mục Quét để nhật ký lưu lại calo và dưỡng chất."
          action={<Button label="Lên mâm hôm nay" onPress={() => goTab('/mam')} />}
        />
      ) : null}

      {dayKcalTotals.length > 0 ? (
        <Card style={{ gap: space.md }}>
          <T v="h2" accessibilityRole="header">
            Calo mỗi người theo ngày
          </T>
          <View
            style={{ gap: space.sm }}
            accessibilityLabel={`Biểu đồ calo tuần ${week}: ${trays} mâm đã nấu, ${quickEntries.length} bữa quét nhanh`}>
            {dayKcalTotals.map((d) => {
              const date = new Date(`${d.date}T00:00:00`);
              const onTarget =
                d.totalKcal != null &&
                d.e_target_kcal != null &&
                Math.abs(d.totalKcal - d.e_target_kcal) <= d.e_target_kcal * 0.1;
              return (
                <View key={d.date} style={{ gap: 4 }}>
                  <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                    <T v="label">
                      {WD[date.getDay()]} {date.getDate()}/{date.getMonth() + 1}
                    </T>
                    <T testID="kcal-value" tabular tone={d.totalKcal == null ? 'muted' : 'text'}>
                      {d.totalKcal == null
                        ? 'chưa ghi'
                        : `${Math.round(d.totalKcal)} kcal${d.e_target_kcal ? ` / mục tiêu ${Math.round(d.e_target_kcal)}` : ''}`}
                    </T>
                  </Row>
                  <View style={{ height: 8, borderRadius: radius.sm, backgroundColor: c.surfaceAlt }}>
                    {d.totalKcal != null ? (
                      <View
                        style={{
                          width: `${Math.min(100, (d.totalKcal / max) * 100)}%`,
                          height: 8,
                          borderRadius: radius.sm,
                          backgroundColor: onTarget ? c.herb : c.macro.kcal,
                        }}
                      />
                    ) : null}
                    {d.e_target_kcal ? (
                      <View
                        style={{
                          position: 'absolute',
                          left: `${Math.min(100, (d.e_target_kcal / max) * 100)}%`,
                          top: -2,
                          bottom: -2,
                          width: 2.5,
                          backgroundColor: c.text,
                        }}
                      />
                    ) : null}
                  </View>
                </View>
              );
            })}
          </View>
          <T v="small" tone="muted" tabular>
            {sampleTarget != null
              ? `Mục tiêu: ${Math.round(sampleTarget)} kcal/ngày (vạch dọc). Ngày chưa ghi không tính calo.`
              : 'Vạch dọc là mục tiêu năng lượng (nếu đã đặt). Ngày chưa ghi không tính calo.'}
          </T>

          <View
            accessibilityLabel="Bảng tóm tắt calo và lô dùng kịp theo ngày"
            style={{ borderTopWidth: 1, borderTopColor: c.hairline, paddingTop: space.sm, gap: space.xs }}>
            <Row style={{ backgroundColor: c.surfaceAlt, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 6, flexWrap: 'nowrap' }}>
              <T v="small" style={{ flex: 2, fontWeight: '600' }}>Ngày</T>
              <T v="small" style={{ flex: 1, textAlign: 'right', fontWeight: '600' }}>Số mâm</T>
              <T v="small" style={{ flex: 2, textAlign: 'right', fontWeight: '600' }}>Calo</T>
              <T v="small" style={{ flex: 1, textAlign: 'right', fontWeight: '600' }}>Lô kịp</T>
            </Row>
            {dayKcalTotals.map((d) => {
              const date = new Date(`${d.date}T00:00:00`);
              return (
                <Row
                  key={`tbl-${d.date}`}
                  style={{
                    paddingHorizontal: space.sm,
                    paddingVertical: 4,
                    borderBottomWidth: 1,
                    borderBottomColor: c.hairline,
                    flexWrap: 'nowrap',
                  }}>
                  <T v="small" style={{ flex: 2 }}>
                    {WD[date.getDay()]} {date.getDate()}/{date.getMonth() + 1}
                  </T>
                  <T v="small" tabular style={{ flex: 1, textAlign: 'right' }}>
                    {d.cooked_trays + d.quickCount}
                  </T>
                  <T v="small" tabular style={{ flex: 2, textAlign: 'right' }} tone={d.totalKcal == null ? 'muted' : 'text'}>
                    {d.totalKcal == null ? 'Chưa ghi' : `${Math.round(d.totalKcal)}`}
                  </T>
                  <T v="small" tabular style={{ flex: 1, textAlign: 'right' }}>
                    {d.urgent_lots_used}
                  </T>
                </Row>
              );
            })}
          </View>
        </Card>
      ) : null}

      {macroRows.length > 0 ? (
        <Card style={{ gap: space.md }}>
          <Row style={{ justifyContent: 'space-between', flexWrap: 'wrap' }} gap={space.xs}>
            <T v="h2" accessibilityRole="header">
              Dinh dưỡng trong tuần
            </T>
            <T v="small" tone="muted">
              Tỷ lệ theo năng lượng (kcal)
            </T>
          </Row>
          <View style={{ gap: space.sm }}>
            {macroRows.map((m) => (
              <View key={m.key} style={{ gap: 4 }} accessibilityLabel={`${m.label} ${Math.round(m.grams)} gam, ${m.pct}%`}>
                <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                  <T v="label">{m.label}</T>
                  <T v="label" tabular testID="macro-value">
                    {Math.round(m.grams)} g ({m.pct}%)
                  </T>
                </Row>
                <View style={{ height: 8, borderRadius: radius.sm, backgroundColor: c.surfaceAlt, overflow: 'hidden' }}>
                  <View style={{ width: `${Math.min(100, m.pct)}%`, height: 8, borderRadius: radius.sm, backgroundColor: m.color }} />
                </View>
              </View>
            ))}
            <View
              style={{
                borderTopWidth: 1,
                borderTopColor: c.hairline,
                paddingTop: space.sm,
                gap: 4,
              }}
              accessibilityLabel={`Chất xơ ${Math.round(wkFiberG)} gam`}>
              <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                <T v="label">Chất xơ (tính riêng)</T>
                <T v="label" tabular testID="macro-fiber-value">
                  {Math.round(wkFiberG)} g
                </T>
              </Row>
              <View style={{ height: 6, borderRadius: radius.sm, backgroundColor: c.surfaceAlt, overflow: 'hidden' }}>
                <View
                  style={{
                    width: `${Math.min(100, Math.round((wkFiberG / 175) * 100))}%`,
                    height: 6,
                    borderRadius: radius.sm,
                    backgroundColor: c.macro.fiber,
                  }}
                />
              </View>
            </View>
          </View>
        </Card>
      ) : null}
    </View>
  ) : null;

  const rightCol = showContent ? (
    <View style={{ gap: space.xl }}>
      <Section
        title="Bữa đã quét và ghi nhanh"
        right={
          <Button
            kind="ghost"
            compact
            label="Quét món"
            onPress={() => router.push({ pathname: '/quet', params: { tab: 'calorie' } })}
            style={{ paddingHorizontal: space.sm }}
          />
        }>
        <View testID="journal-quick-logs">
          {quickEntries.length > 0 ? (
            <Card style={{ padding: 0, gap: 0, overflow: 'hidden' }}>
              {quickEntries.map((entry, idx) => {
                const d = new Date(`${entry.date}T00:00:00`);
                return (
                  <View
                    key={entry.id}
                    testID={`quick-log-item-${entry.id}`}
                    style={{
                      padding: space.lg,
                      gap: space.xs,
                      borderTopWidth: idx > 0 ? 1 : 0,
                      borderTopColor: c.hairline,
                    }}>
                    <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }} gap={space.xs}>
                      <Row gap={space.xs} style={{ flex: 1, minWidth: 0 }}>
                        <View style={{ backgroundColor: c.accentSoft, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 2, maxWidth: '100%', flexShrink: 1 }}>
                          <T v="small" tone="accent" style={{ fontWeight: '600', flexShrink: 1 }}>
                            Bữa {MEAL_SLOT_LABEL[entry.meal_slot]}
                          </T>
                        </View>
                        <T v="small" tone="muted" tabular style={{ flexShrink: 1 }}>
                          {WD[d.getDay()]} {d.getDate()}/{d.getMonth() + 1}, {entry.portion_label}
                        </T>
                      </Row>
                      <T v="label" tone="accent" tabular style={{ flexShrink: 0 }}>
                        {Math.round(entry.kcal)} kcal
                      </T>
                    </Row>

                    <T v="title">{entry.title_vi}</T>

                    {entry.modifiers_vi.length > 0 ? (
                      <T v="small" tone="muted">
                        Điều chỉnh: {entry.modifiers_vi.join(', ')}
                      </T>
                    ) : null}

                    <Row style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                      <T v="small" tone="muted" tabular>
                        Đạm {entry.protein_g}g, Tinh bột {entry.carbs_g}g, Béo {entry.fat_g}g
                      </T>
                      <Button
                        kind="ghost"
                        compact
                        label="Xoá"
                        testID={`quick-log-delete-${entry.id}`}
                        onPress={() => void handleDeleteQuickLog(entry.id)}
                      />
                    </Row>
                  </View>
                );
              })}
            </Card>
          ) : (
            <View style={{ backgroundColor: c.surfaceAlt, borderRadius: radius.md, padding: space.lg, gap: space.xs }}>
              <T tone="muted">Chưa có món ăn hay mã vạch nào được ghi nhanh trong tuần này.</T>
            </View>
          )}
        </View>
      </Section>

      <Section title="Lịch sử bữa đã nấu">
        {history.length ? (
          <Card style={{ padding: 0, gap: 0, overflow: 'hidden' }}>
            {history.map((m, idx) => {
              const d = new Date(`${m.date}T00:00:00`);
              return (
                <View
                  key={m.cook_session_id}
                  style={{
                    gap: space.sm,
                    padding: space.lg,
                    borderTopWidth: idx > 0 ? 1 : 0,
                    borderTopColor: c.hairline,
                  }}>
                  <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                    <T v="label">
                      {WD[d.getDay()]} {d.getDate()}/{d.getMonth() + 1}, {MEAL_LABEL[m.meal]}
                    </T>
                    <T v="small" tone="muted" tabular>
                      {m.persons} người{m.kcal_per_person != null ? `, ${Math.round(m.kcal_per_person)} kcal/người` : ''}
                    </T>
                  </Row>
                  <View style={{ gap: space.xs }}>
                    {m.dishes.map((dish) => (
                      <Pressable
                        key={`${m.cook_session_id}-${dish.recipe_id}`}
                        accessibilityRole="button"
                        accessibilityLabel={`Xem công thức ${dish.name_vi}`}
                        onPress={() => router.push({ pathname: '/mon/[id]', params: { id: dish.recipe_id } })}
                        style={({ pressed }) => ({
                          minHeight: TOUCH,
                          borderRadius: radius.sm,
                          paddingHorizontal: space.md,
                          justifyContent: 'center',
                          backgroundColor: pressed ? c.hairline : c.surfaceAlt,
                        })}>
                        <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                          <T style={{ flexShrink: 1 }}>
                            <T v="label" tone="accent">
                              {SLOT_LABEL[dish.slot]}:{' '}
                            </T>
                            {dish.name_vi}
                          </T>
                          {dish.kcal_per_person != null ? (
                            <T v="small" tone="muted" tabular>
                              {Math.round(dish.kcal_per_person)} kcal
                            </T>
                          ) : null}
                        </Row>
                      </Pressable>
                    ))}
                  </View>
                </View>
              );
            })}
          </Card>
        ) : (
          <View style={{ backgroundColor: c.surfaceAlt, borderRadius: radius.md, padding: space.lg }}>
            <T tone="muted">Chưa có bữa nấu nào hoàn tất trong tuần này.</T>
          </View>
        )}
      </Section>
    </View>
  ) : null;

  return (
    <Screen testID="screen-journal">
      <View style={{ gap: 2 }}>
        <T v="small" style={{ color: c.herb, fontFamily: font.semibold }}>
          Sổ dinh dưỡng gia đình
        </T>
        <T v="huge" accessibilityRole="header">
          Nhật ký bữa ăn
        </T>
        <T tone="muted">Theo dõi calo, đa lượng từng ngày từ mâm đã nấu và món ăn quét nhanh trong tuần.</T>
      </View>

      <View
        style={{
          backgroundColor: c.surface,
          borderRadius: radius.lg,
          borderWidth: 1,
          borderColor: c.hairline,
          paddingVertical: space.sm,
          paddingHorizontal: isMobile ? space.sm : space.md,
        }}>
        <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap', alignItems: 'center' }} gap={space.xs}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Tuần trước"
            onPress={() => setOffset(offset - 1)}
            style={({ pressed }) => ({
              minHeight: 40,
              paddingHorizontal: isMobile ? space.xs : space.md,
              borderRadius: radius.sm,
              flexDirection: 'row',
              alignItems: 'center',
              gap: isMobile ? 2 : space.xs,
              flexShrink: 0,
              backgroundColor: pressed ? c.surfaceAlt : 'transparent',
            })}>
            <Icon name="chevron-left" size={18} color={c.accent} />
            <T v={isMobile ? 'small' : 'label'} tone="accent" numberOfLines={1} style={{ fontWeight: '600' }}>
              Tuần trước
            </T>
          </Pressable>

          <T v={isMobile ? 'label' : 'title'} tabular numberOfLines={1} style={{ flexShrink: 0 }}>
            Tuần {week.split('-W')[1]}/{week.split('-W')[0]}
          </T>

          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Tuần sau"
            disabled={offset >= 0}
            onPress={() => setOffset(offset + 1)}
            style={({ pressed }) => ({
              minHeight: 40,
              paddingHorizontal: isMobile ? space.xs : space.md,
              borderRadius: radius.sm,
              flexDirection: 'row',
              alignItems: 'center',
              gap: isMobile ? 2 : space.xs,
              flexShrink: 0,
              opacity: offset >= 0 ? 0.4 : 1,
              backgroundColor: pressed && offset < 0 ? c.surfaceAlt : 'transparent',
            })}>
            <T v={isMobile ? 'small' : 'label'} tone="accent" numberOfLines={1} style={{ fontWeight: '600' }}>
              Tuần sau
            </T>
            <Icon name="chevron-right" size={18} color={c.accent} />
          </Pressable>
        </Row>
      </View>

      {q.isLoading && !quickEntries.length ? <Loading /> : null}
      {q.error ? <ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} /> : null}

      {showContent ? (
        isDesktop ? (
          <View style={{ flexDirection: 'row', gap: space.xl, alignItems: 'flex-start' }}>
            <View style={{ flex: 7, minWidth: 0 }}>{leftCol}</View>
            <View style={{ flex: 5, minWidth: 0 }}>{rightCol}</View>
          </View>
        ) : (
          <>
            {leftCol}
            {rightCol}
          </>
        )
      ) : null}
    </Screen>
  );
}
