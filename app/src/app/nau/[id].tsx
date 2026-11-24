import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useMemo } from 'react';
import { useWindowDimensions, View } from 'react-native';

import { api, call, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { Icon, SLOT_LABEL } from '@/components/domain';
import { Button, Card, ErrorBox, Loading, Notice, Row, Screen, Section, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { fmtClock, fmtLeft, stepKey, useCookSession, useDoneSteps, useNow, useScreenOn } from '@/lib/cooking';
import { goTab } from '@/lib/nav';
import { radius, size, space, useTheme } from '@/theme';

type Entry = Schemas['ScheduleEntry'];

/** Nấu cả mâm (UC19): per-dish CP-SAT timeline, current step, absolute-timestamp multi-timers & finished-waiting banner. */
export default function Cooking() {
  const { id } = useLocalSearchParams<{ id: string }>();
  useScreenOn(`cook-${id}`);
  const router = useRouter();
  const qc = useQueryClient();
  const { c } = useTheme();
  const { width } = useWindowDimensions();
  const desktop = width >= 1024;
  const q = useCookSession(id);
  const catalog = useCatalog();
  const plan = useQuery({
    queryKey: ['plan', q.data?.meal_plan_id],
    queryFn: () => call(api.GET('/meal-plans/{id}', { params: { path: { id: q.data!.meal_plan_id } } })),
    enabled: !!q.data,
  });
  const { done, mark } = useDoneSteps(id);
  const now = useNow();
  const abandon = useMutation({
    mutationFn: () => call(api.POST('/cook-sessions/{id}/abandon', { params: { path: { id } } })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['plan'] });
      goTab('/mam');
    },
  });

  const s = q.data;
  useEffect(() => {
    if (s && s.status === 'completed') router.replace({ pathname: '/nau-xong/[id]', params: { id } });
  }, [s, id, router]);

  const view = useMemo(() => {
    if (!s) return null;
    const base = new Date(s.started_at).getTime();
    const end = Math.max(1, ...s.schedule.map((e) => e.end_offset_s), s.makespan_s);
    const byRecipe = new Map<string, Entry[]>();
    s.schedule.forEach((e) => byRecipe.set(e.recipe_id, [...(byRecipe.get(e.recipe_id) ?? []), e]));
    return { base, end, byRecipe };
  }, [s]);

  if (q.isLoading) return <Screen><Loading /></Screen>;
  if (q.error || !s || !view) return <Screen><ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} /></Screen>;

  const name = (rid: string) =>
    plan.data?.items.find((i) => i.recipe_id === rid && i.status === 'active')?.recipe_name_vi ??
    catalog.recipes.get(rid)?.name_vi ??
    'Món';
  const slot = (rid: string) => plan.data?.items.find((i) => i.recipe_id === rid)?.slot;
  const elapsed = (now - view.base) / 1000;
  const ordered = [...s.schedule].sort((a, b) => a.start_offset_s - b.start_offset_s);
  const pendingActive = ordered.filter((e) => e.kind === 'active' && !done.includes(stepKey(e)));
  const current = pendingActive[0];
  const next = pendingActive[1];
  const running = ordered
    .filter((e) => e.kind === 'passive' && elapsed >= e.start_offset_s && elapsed < e.end_offset_s && !done.includes(stepKey(e)))
    .sort((a, b) => a.end_offset_s - b.end_offset_s);
  const finishedWaiting = ordered
    .filter((e) => e.kind === 'passive' && elapsed >= e.end_offset_s && !done.includes(stepKey(e)))
    .sort((a, b) => a.end_offset_s - b.end_offset_s);

  const serveAt = new Date(s.serve_at).getTime();
  const late = current ? elapsed - current.start_offset_s : 0;

  const ganttCard = (
    <Card style={{ gap: space.md }}>
      <T v="h2" accessibilityRole="header">
        Lịch bếp song song
      </T>
      {view.byRecipe.size
        ? [...view.byRecipe.entries()].map(([rid, steps]) => (
          <View key={rid} style={{ gap: 4 }}>
            <T v="label">
              {slot(rid) ? `${SLOT_LABEL[slot(rid)!]}: ` : ''}
              {name(rid)}
            </T>
            <View style={{ height: 18, borderRadius: radius.sm, backgroundColor: c.surfaceAlt }}>
              {steps.map((e) => {
                const isDone = done.includes(stepKey(e));
                const isPassive = e.kind === 'passive';
                return (
                  <View
                    key={e.step_no}
                    style={{
                      position: 'absolute',
                      left: `${(e.start_offset_s / view.end) * 100}%`,
                      width: `${Math.max(1.5, ((e.end_offset_s - e.start_offset_s) / view.end) * 100)}%`,
                      top: isPassive ? 5 : 0,
                      bottom: isPassive ? 5 : 0,
                      borderRadius: 4,
                      backgroundColor: isDone ? c.border : isPassive ? c.herbSoft : c.accent,
                      borderWidth: isPassive ? 2 : 0,
                      borderColor: isPassive ? (isDone ? c.border : c.herb) : 'transparent',
                    }}
                  />
                );
              })}
              <View
                style={{
                  position: 'absolute',
                  left: `${Math.min(100, Math.max(0, (elapsed / view.end) * 100))}%`,
                  top: -3,
                  bottom: -3,
                  width: 2,
                  backgroundColor: c.text,
                }}
              />
            </View>
          </View>
        ))
        : null}
      <T v="small" tone="muted" tabular>
        Thanh màu nổi (cao): đứng bếp. Xanh viền (thanh mảnh): chờ tự động. Vạch dọc: bây giờ ({fmtClock(now)}).
      </T>
    </Card>
  );

  const stepsCol = (
    <View style={{ gap: space.lg }}>
      {current ? (
        <Card testID="cook-current" style={{ borderColor: c.accent, borderWidth: 2, backgroundColor: c.surface, gap: space.md }}>
          <T v="small" tone="muted" tabular>
            Bước hiện tại: {name(current.recipe_id)}, bước {current.step_no}
          </T>
          <T v="h1" style={{ fontSize: size.xl, lineHeight: 32 }}>
            {current.text_vi}
          </T>
          <T tone="muted" tabular>
            {late < 0
              ? `Bắt đầu lúc ${fmtClock(view.base + current.start_offset_s * 1000)} (còn ${fmtLeft(-late * 1000)})`
              : `Dự kiến xong lúc ${fmtClock(view.base + current.end_offset_s * 1000)}`}
          </T>
          {next ? (
            <T>
              <T v="label">Tiếp theo:</T> {name(next.recipe_id)}: {next.text_vi}
            </T>
          ) : null}
          <Button label="Xong bước này" testID="cook-step-done" onPress={() => mark(stepKey(current))} />
        </Card>
      ) : (
        <Notice tone="ok">
          <T>Đã xong mọi bước phải đứng bếp. Chờ các món đang ninh rồi bấm &quot;Nấu xong&quot;.</T>
        </Notice>
      )}

      {finishedWaiting.length ? (
        <Section title="Đã xong giờ chờ">
          {finishedWaiting.map((e) => (
            <Notice key={stepKey(e)} tone="warn">
              <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <T v="label">
                    {name(e.recipe_id)}: {e.text_vi}
                  </T>
                  <T v="small" tone="muted" tabular>
                    Đã hết giờ chờ lúc {fmtClock(view.base + e.end_offset_s * 1000)}
                  </T>
                </View>
                <Button label="Xác nhận xong" kind="secondary" onPress={() => mark(stepKey(e))} />
              </Row>
            </Notice>
          ))}
        </Section>
      ) : null}

      {running.length ? (
        <Section title="Đang chờ">
          {running.map((e) => {
            const endAt = view.base + e.end_offset_s * 1000;
            return (
              <Card key={stepKey(e)}>
                <Row style={{ flexWrap: 'nowrap' }}>
                  <Icon name="clock" color={c.accent} />
                  <T v="label" style={{ flexShrink: 1 }}>
                    {name(e.recipe_id)}: {e.text_vi}
                  </T>
                </Row>
                <T v="h2" tabular testID="timer-value" accessibilityLiveRegion="polite">
                  còn {fmtLeft(endAt - now)}, xong lúc {fmtClock(endAt)}
                </T>
              </Card>
            );
          })}
        </Section>
      ) : null}

      <Section title="Toàn bộ lịch">
        {ordered.map((e) => {
          const isDone = done.includes(stepKey(e));
          return (
            <Row key={stepKey(e)} style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
              <T v="label" tone={isDone ? 'muted' : 'accent'} tabular style={{ width: 52 }}>
                {fmtClock(view.base + e.start_offset_s * 1000)}
              </T>
              <T tone={isDone ? 'muted' : 'text'} style={{ flex: 1 }}>
                {name(e.recipe_id)}: {e.text_vi}
                {e.kind === 'passive' ? ' (chờ)' : ''}
              </T>
              {isDone ? <Icon name="check" size={16} color={c.herb} /> : null}
            </Row>
          );
        })}
      </Section>
    </View>
  );

  return (
    <Screen
      testID="screen-cooking"
      footer={
        s.status === 'in_progress' ? (
          <>
            <Button label="Nấu xong" testID="cook-finish" onPress={() => router.push({ pathname: '/nau-xong/[id]', params: { id } })} />
            <Button label="Bỏ phiên nấu" kind="ghost" onPress={() => abandon.mutate()} loading={abandon.isPending} />
          </>
        ) : undefined
      }>
      <View style={{ gap: space.xs }}>
        <T v="h1" accessibilityRole="header">
          Nấu cả mâm
        </T>
        <T tone="muted" tabular>
          Dọn mâm lúc {fmtClock(serveAt)}. Món lâu nhất bắt đầu trước, màn hình luôn sáng khi nấu.
        </T>
      </View>

      {s.status !== 'in_progress' ? (
        <Notice tone="warn">
          <T>Phiên nấu này {s.status === 'abandoned' ? 'đã bỏ' : s.status === 'reverted' ? 'đã hoàn tác' : 'đã kết thúc'}.</T>
          <Button label="Về Mâm cơm hôm nay" kind="secondary" onPress={() => goTab('/mam')} />
        </Notice>
      ) : null}

      {desktop ? (
        <View style={{ flexDirection: 'row', gap: space.xl, alignItems: 'flex-start' }}>
          <View style={{ flex: 7, minWidth: 0 }}>{stepsCol}</View>
          <View style={{ flex: 5, minWidth: 0 }}>{ganttCard}</View>
        </View>
      ) : (
        <>
          {ganttCard}
          {stepsCol}
        </>
      )}

      {abandon.error ? <ErrorBox message={errorText(abandon.error)} /> : null}
    </Screen>
  );
}
