import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { type Href, useNavigation, useRouter } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { AppState, Pressable, View } from 'react-native';

import { api, call } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { recipePhotoFor } from '@/components/Brand';
import { FreshBadge, Icon, type IconName, SLOT_LABEL } from '@/components/domain';
import { QUICK_STAPLES } from '@/components/pantryForms';
import { BroadsheetLedgerFrame, Button, Card, Chip, ErrorBox, Loading, Rise, Row, Screen, Section, Skeleton, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { isoWeekKey, localDateString, useQuickMealLogs } from '@/lib/mealLog';
import { getProgress } from '@/lib/onboarding';
import { formatFriendlyQty, groupLotsByIngredient } from '@/lib/pantryDisplay';
import { currentMeal, MEAL_LABEL, qk, useLatestPlan, useLots, useProfile } from '@/lib/queries';
import { font, radius, space, TOUCH, useLayout, useTheme } from '@/theme';

const SLOT_ORDER = { man: 0, rau: 1, canh: 2 } as const;

const STARTER_POOL = [...QUICK_STAPLES, 'Cải ngọt', 'Nấm rơm'] as const;

export default function Home() {
  const router = useRouter();
  const qc = useQueryClient();
  const nav = useNavigation() as { addListener?: (ev: string, cb: () => void) => () => void };
  const { c } = useTheme();
  const { isDesktop, isMobile, isTinyPhone } = useLayout();
  const { user, status } = useSession();
  const catalog = useCatalog();
  const profile = useProfile();
  const lots = useLots();
  const [nowTs, setNowTs] = useState(() => Date.now());
  const today = new Date(nowTs);
  const meal = currentMeal(today);
  const plan = useLatestPlan(meal);
  const week = isoWeekKey(today);
  const journalQ = useQuery({
    queryKey: qk.journal(week),
    queryFn: () => call(api.GET('/journal', { params: { query: { week } } })),
    enabled: status === 'signedIn',
  });
  const quickLogsQ = useQuickMealLogs(week);
  const [checked, setChecked] = useState(false);
  const [starterBusy, setStarterBusy] = useState<string | null>(null);
  const [starterMsg, setStarterMsg] = useState<string | null>(null);

  useEffect(() => {
    const bump = () => setNowTs(Date.now());
    const unsub = typeof nav?.addListener === 'function' ? nav.addListener('focus', bump) : undefined;
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active') bump();
    });
    return () => {
      unsub?.();
      sub.remove();
    };
  }, [nav]);

  useEffect(() => {
    if (!user || !profile.data || checked) return;
    const p = profile.data;
    const started = p.updated_at !== null || p.allergen_codes.length > 0 || p.favorite_recipe_ids.length > 0 || p.diet_code !== null;
    getProgress(user.id).then((pr) => {
      setChecked(true);
      if (!pr.done && !started) router.replace(pr.consent ? '/onboarding/ho-so' : '/onboarding');
    });
  }, [user, profile.data, checked, router]);

  const allLots = useMemo(() => lots.data?.items ?? [], [lots.data]);
  const groupedLots = useMemo(() => groupLotsByIngredient(allLots), [allLots]);
  const soon = useMemo(
    () => groupedLots.filter((g) => ['dung_ngay', 'dung_som', 'kiem_tra'].includes(g.freshness_label)),
    [groupedLots],
  );
  const isStaff = user?.role === 'admin' || user?.role === 'ml_operator';
  const active = plan.data ? plan.data.items.filter((i) => i.status === 'active') : [];
  const ordered = [...active].sort((a, b) => SLOT_ORDER[a.slot] - SLOT_ORDER[b.slot]);
  const dateLine = `${['Chủ nhật', 'Thứ hai', 'Thứ ba', 'Thứ tư', 'Thứ năm', 'Thứ sáu', 'Thứ bảy'][today.getDay()]}, ${today.getDate()} tháng ${today.getMonth() + 1}`;

  // Compute live kcal eaten today cleanly (deduplicated against server journal)
  const todayStr = localDateString(today);
  const serverIds = new Set((journalQ.data?.meal_logs ?? []).map((m) => m.id));
  const todayDay = (journalQ.data?.days ?? []).find((d) => d.date === todayStr);
  const uncountedKcal = (quickLogsQ.data ?? [])
    .filter((e) => e.date === todayStr && !serverIds.has(e.id))
    .reduce((s, e) => s + e.kcal, 0);
  const todayTotalKcal = Math.round((todayDay?.kcal_per_person ?? 0) + uncountedKcal);
  const todayTarget = todayDay?.e_target_kcal ?? profile.data?.kcal_target ?? null;
  const todayPct = todayTarget && todayTarget > 0 ? Math.min(100, Math.round((todayTotalKcal / todayTarget) * 100)) : 0;

  const quickAddStarter = async (name: string) => {
    setStarterBusy(name);
    setStarterMsg(null);
    try {
      const res = await call(api.GET('/ingredients', { params: { query: { q: name, limit: 5 } } }));
      const ing = res.items.find((i) => i.name_vi.toLowerCase() === name.toLowerCase()) ?? res.items[0];
      if (!ing) return;
      const quantity = ing.units.length
        ? { count: 1, unit_code: ing.units[0].unit_code }
        : ing.countable
          ? { g_min: 200, g_max: 200 }
          : { qty_level: 'vua' as const };
      await call(api.POST('/pantry/lots', { body: { ingredient_id: ing.id, quantity } }));
      await qc.invalidateQueries({ queryKey: ['lots'] });
      setStarterMsg(`Đã thêm ${ing.name_vi} vào Tủ lạnh.`);
    } finally {
      setStarterBusy(null);
    }
  };

  const todayNutritionCard = (
    <Card testID="home-today-kcal" style={{ gap: space.sm }}>
      <Row style={{ justifyContent: 'space-between', alignItems: 'center' }} gap={space.sm}>
        <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
          <T v="label">Hôm nay đã ăn</T>
          <Row gap={space.xs} style={{ alignItems: 'baseline' }}>
            <T v="h1" tabular tone="accent">
              {todayTotalKcal} kcal
            </T>
            {todayTarget ? (
              <T v="small" tone="muted" tabular>
                / mục tiêu {Math.round(todayTarget)} kcal
              </T>
            ) : null}
          </Row>
        </View>
        <Button
          label="+ Ghi bữa"
          kind="secondary"
          compact
          testID="home-quick-log-btn"
          onPress={() => router.push({ pathname: '/quet', params: { tab: 'calorie' } })}
        />
      </Row>
      {todayTarget ? (
        <View style={{ height: 8, borderRadius: radius.pill, backgroundColor: c.surfaceAlt, overflow: 'hidden' }}>
          <View
            style={{
              width: `${todayPct}%`,
              height: 8,
              borderRadius: radius.pill,
              backgroundColor: todayTotalKcal > todayTarget * 1.1 ? c.warn : c.herb,
            }}
          />
        </View>
      ) : (
        <T v="small" tone="muted">
          Chưa đặt mục tiêu calo/ngày — cài đặt bất cứ lúc nào nếu bạn muốn theo dõi cân nặng.
        </T>
      )}
    </Card>
  );

  const mealHero = (
    <View>
      {plan.isLoading ? <Skeleton height={220} r={radius.lg} /> : null}
      {plan.error ? <ErrorBox message={errorText(plan.error)} onRetry={() => plan.refetch()} /> : null}
      {plan.data ? (
        <Rise>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Mở ${MEAL_LABEL[meal].toLowerCase()}: ${ordered.map((i) => i.recipe_name_vi).join(', ')}`}
            onPress={() => router.push('/mam')}
            testID="home-latest-plan">
            {({ pressed }) => (
              <BroadsheetLedgerFrame
                title={`${plan.data!.status === 'accepted' ? 'Mâm đã chọn' : 'Gợi ý mâm cơm'}, ${plan.data!.persons} người`}
                rightText="Mở Nấu ăn →"
                accentTone="herb"
                style={{ transform: [{ scale: pressed ? 0.99 : 1 }] }}
                innerStyle={{ padding: 0, gap: 0 }}>
                <View>
                  {ordered.map((i, idx) => {
                    const dishPhoto = recipePhotoFor(i.recipe_name_vi, i.slot);
                    return (
                      <Row
                        key={i.id}
                        gap={space.md}
                        style={{
                          paddingHorizontal: space.lg,
                          paddingVertical: space.md,
                          borderTopWidth: idx > 0 ? 1 : 0,
                          borderTopColor: c.hairline,
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          flexWrap: 'nowrap',
                        }}>
                        <Row gap={space.md} style={{ flex: 1, minWidth: 0, flexWrap: 'nowrap' }}>
                          {dishPhoto ? (
                            <Image
                              source={dishPhoto}
                              contentFit="cover"
                              style={{ width: 52, height: 52, borderRadius: radius.sm, backgroundColor: c.surfaceAlt }}
                              accessibilityLabel={i.recipe_name_vi}
                            />
                          ) : (
                            <View
                              style={{
                                width: 52,
                                height: 52,
                                borderRadius: radius.sm,
                                backgroundColor: c.accentSoft,
                                alignItems: 'center',
                                justifyContent: 'center',
                              }}>
                              <T v="small" tone="accent" style={{ fontFamily: font.semibold }}>
                                {SLOT_LABEL[i.slot]}
                              </T>
                            </View>
                          )}
                          <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
                            <T v="small" tone="herb" style={{ fontFamily: font.semibold }}>
                              Món {SLOT_LABEL[i.slot].toLowerCase()}
                            </T>
                            <T v="title" style={{ fontFamily: font.semibold }} numberOfLines={2}>
                              {i.recipe_name_vi}
                            </T>
                          </View>
                        </Row>
                        {i.kcal_per_person != null ? (
                          <View style={{ backgroundColor: c.surfaceAlt, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.sm }}>
                            <T v="small" tone="text" tabular>
                              {Math.round(i.kcal_per_person)} kcal
                            </T>
                          </View>
                        ) : null}
                      </Row>
                    );
                  })}
                  <Row
                    style={{
                      paddingHorizontal: space.lg,
                      paddingVertical: space.sm,
                      borderTopWidth: 1,
                      borderTopColor: c.hairline,
                      backgroundColor: c.surfaceAlt,
                      justifyContent: 'space-between',
                    }}>
                    <T v="small" tone="muted">
                      Mâm cơm {ordered.length} món
                    </T>
                    <T v="small" tone="muted" tabular>
                      {plan.data!.rice_bowls_per_person != null
                        ? `Cơm ${String(plan.data!.rice_bowls_per_person).replace('.', ',')} bát / người`
                        : 'Ăn kèm cơm trắng'}
                    </T>
                  </Row>
                </View>
              </BroadsheetLedgerFrame>
            )}
          </Pressable>
        </Rise>
      ) : plan.data === null ? (
        <Card style={{ gap: space.md }}>
          <View style={{ gap: 4 }}>
            <T v="h2" accessibilityRole="header">
              {meal === 'lunch' ? 'Trưa nay ăn gì?' : 'Tối nay nấu gì?'}
            </T>
            <T tone="muted">
              Xem ngay các món nấu nhanh trong 15–30 phút từ nguyên liệu đang có trong tủ, hoặc ghép đủ mâm cơm 3 món.
            </T>
          </View>
          <Row gap={space.sm}>
            <Button label="Nấu nhanh 1–2 món" testID="home-make-plan" onPress={() => router.push('/mam')} />
            <Button
              kind="secondary"
              label="Tìm công thức"
              onPress={() => router.push('/kham-pha' as Href)}
            />
          </Row>
        </Card>
      ) : null}
    </View>
  );

  const scanTiles = (
    <View style={{ gap: space.md }}>
      <ActionTile
        primary
        title="Chụp món tính calo"
        sub="Nhận diện món ăn, nhiều đĩa trên mâm, chỉnh suất & ghi Nhật ký"
        icon="camera"
        testID="home-scan-calorie"
        onPress={() => router.push({ pathname: '/quet', params: { tab: 'calorie' } })}
      />
      <Row style={{ flexWrap: isTinyPhone ? 'wrap' : 'nowrap', alignItems: 'stretch' }} gap={space.md}>
        <ActionTile
          title="Thêm đồ tủ lạnh"
          sub="Chụp đồ mới mua, tự điền tên & số lượng"
          icon="bag"
          testID="home-scan-haul"
          onPress={() => router.push({ pathname: '/quet', params: { mode: 'haul' } })}
        />
        <ActionTile
          title="Kiểm kê tủ lạnh"
          sub="Chụp cả ngăn tủ để rà đồ sắp hỏng"
          icon="sliders"
          testID="home-scan-fridge"
          onPress={() => router.push({ pathname: '/quet', params: { mode: 'fridge' } })}
        />
      </Row>
    </View>
  );

  const priorityOrStarterSection = (
    <Section
      title={groupedLots.length === 0 ? 'Bắt đầu nhanh Tủ lạnh' : 'Sắp hỏng cần dùng trước'}
      right={<Button kind="ghost" label="Mở Tủ lạnh" onPress={() => router.push('/kho')} style={{ paddingHorizontal: space.sm }} />}>
      {lots.isLoading ? <Loading rows={1} /> : null}
      {lots.error ? <ErrorBox message={errorText(lots.error)} onRetry={() => lots.refetch()} /> : null}
      {lots.data && groupedLots.length === 0 ? (
        <Card testID="home-starter-pantry" style={{ gap: space.md }}>
          <T tone="muted">
            Chạm chọn vài đồ quen thuộc đang có sẵn trong nhà để nhận ngay gợi ý món tối nay:
          </T>
          <Row gap={space.sm}>
            {STARTER_POOL.map((name) => (
              <Chip
                key={name}
                label={starterBusy === name ? `${name}…` : `+ ${name}`}
                disabled={Boolean(starterBusy)}
                onPress={() => void quickAddStarter(name)}
              />
            ))}
          </Row>
          {starterMsg ? <T v="small" tone="herb">{starterMsg}</T> : null}
        </Card>
      ) : null}
      {lots.data && groupedLots.length > 0 && soon.length === 0 ? (
        <Card style={{ backgroundColor: c.surfaceAlt }}>
          <T tone="muted">
            Tất cả {groupedLots.length} nguyên liệu trong tủ đều đang tươi mới.
          </T>
        </Card>
      ) : null}
      {soon.length ? (
        isDesktop ? (
          <View style={{ gap: space.md }}>
            {Array.from({ length: Math.ceil(soon.slice(0, 6).length / 2) }, (_, rowIdx) => {
              const pair = soon.slice(0, 6).slice(rowIdx * 2, rowIdx * 2 + 2);
              return (
                <View key={`soon-row-${rowIdx}`} style={{ flexDirection: 'row', gap: space.md }}>
                  {pair.map((g) => (
                    <Pressable
                      key={g.ingredient_id}
                      accessibilityRole="button"
                      onPress={() => router.push('/kho')}
                      style={{
                        backgroundColor: c.surface,
                        borderColor: c.hairline,
                        borderWidth: 1,
                        borderRadius: radius.md,
                        padding: space.md,
                        flex: 1,
                        flexBasis: 0,
                        minWidth: 0,
                        gap: 8,
                      }}>
                      <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                        <T v="title" numberOfLines={1} style={{ flexShrink: 1 }}>
                          {g.ingredient_name_vi}
                        </T>
                        <T v="small" tone="muted" tabular>
                          {formatFriendlyQty(g.balance_g_min, g.balance_g_max, catalog.ingredients.get(g.ingredient_id))}
                        </T>
                      </Row>
                      <FreshBadge value={g.freshness_label} small />
                    </Pressable>
                  ))}
                  {pair.length === 1 ? <View style={{ flex: 1, flexBasis: 0, minWidth: 0 }} pointerEvents="none" /> : null}
                </View>
              );
            })}
          </View>
        ) : (
          <View style={{ gap: space.sm }}>
            {soon.slice(0, 4).map((g) => (
              <Pressable
                key={g.ingredient_id}
                accessibilityRole="button"
                onPress={() => router.push('/kho')}
                style={{
                  backgroundColor: c.surface,
                  borderColor: c.hairline,
                  borderWidth: 1,
                  borderRadius: radius.md,
                  padding: space.md,
                  flexDirection: 'row',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: space.sm,
                }}>
                <View style={{ flex: 1, minWidth: 0, gap: 4 }}>
                  <T v="title" numberOfLines={1}>
                    {g.ingredient_name_vi}
                  </T>
                  <FreshBadge value={g.freshness_label} small />
                </View>
                <T v="label" tone="muted" tabular>
                  {formatFriendlyQty(g.balance_g_min, g.balance_g_max, catalog.ingredients.get(g.ingredient_id))}
                </T>
              </Pressable>
            ))}
          </View>
        )
      ) : null}
    </Section>
  );

  const exploreShortcut = (
    <Card style={{ gap: space.md }}>
      <View style={{ gap: 4 }}>
        <T v="title">Kho công thức cơm nhà</T>
        <T v="body" tone="muted">
          Tìm món theo nguyên liệu có sẵn, thời gian nấu 15–45 phút và dinh dưỡng từng khẩu phần.
        </T>
      </View>
      <Row>
        <Button
          kind="secondary"
          label="Khám phá món ăn"
          testID="home-open-explore-desktop"
          iconRight={<Icon name="arrow-right" size={16} color={c.text} />}
          onPress={() => router.push('/kham-pha' as Href)}
        />
      </Row>
    </Card>
  );

  return (
    <Screen testID="screen-home">
      {isMobile ? (
        <Row style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'nowrap' }} gap={space.sm}>
          <View style={{ flex: 1, minWidth: 0 }}>
            <T v="small" tone="muted">{dateLine}</T>
            <T v="h1" accessibilityRole="header">{MEAL_LABEL[meal]} hôm nay</T>
          </View>
          <Row gap={space.xs} style={{ flexWrap: 'nowrap' }}>
            {isStaff ? (
              <Button
                kind="secondary"
                compact
                label="Quản trị"
                testID="home-open-admin"
                icon={<Icon name="shield" size={16} color={c.info} />}
                onPress={() => router.push('/quan-tri' as Href)}
              />
            ) : null}
            <Button
              kind="secondary"
              compact
              label="Khám phá"
              testID="home-open-explore"
              icon={<Icon name="compass" size={16} color={c.accent} />}
              onPress={() => router.push('/kham-pha' as Href)}
            />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cài đặt"
              testID="open-settings"
              onPress={() => router.push('/cai-dat')}
              style={({ pressed }) => ({
                width: TOUCH,
                height: TOUCH,
                borderRadius: radius.sm,
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: pressed ? c.surfaceAlt : c.surfaceCard,
                borderWidth: 1,
                borderColor: c.hairline,
              })}>
              <Icon name="gear" color={c.text} size={20} />
            </Pressable>
          </Row>
        </Row>
      ) : null}

      {isDesktop ? (
        <View style={{ gap: space.xl }}>
          <Row style={{ justifyContent: 'space-between', alignItems: 'flex-end' }}>
            <View style={{ gap: 4 }}>
              <T v="small" tone="muted">
                {dateLine}
              </T>
              <T v="huge" accessibilityRole="header">
                {MEAL_LABEL[meal]} hôm nay
              </T>
            </View>
            <Row gap={space.sm}>
              <View style={{ backgroundColor: c.surface, borderColor: c.hairline, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: space.md, paddingVertical: 8, maxWidth: '100%', flexShrink: 1 }}>
                <T v="small" tabular>
                  Tủ lạnh: <T v="label" tabular>{groupedLots.length} món</T> · Sắp hỏng: <T v="label" tone="accent" tabular>{soon.length}</T>
                </T>
              </View>
              <Button
                kind="secondary"
                label="Cài đặt"
                testID="open-settings"
                icon={<Icon name="gear" size={18} color={c.text} />}
                onPress={() => router.push('/cai-dat')}
              />
            </Row>
          </Row>
          <View style={{ flexDirection: 'row', gap: space.xl, alignItems: 'flex-start' }}>
            <View style={{ flex: 7, minWidth: 0, gap: space.xl }}>
              {todayNutritionCard}
              {mealHero}
              {priorityOrStarterSection}
            </View>
            <View style={{ flex: 5, minWidth: 0, gap: space.xl }}>
              {scanTiles}
              {exploreShortcut}
            </View>
          </View>
        </View>
      ) : (
        <>
          {todayNutritionCard}
          {mealHero}
          {scanTiles}
          {priorityOrStarterSection}
        </>
      )}
    </Screen>
  );
}

function ActionTile({
  title,
  sub,
  icon,
  primary,
  onPress,
  testID,
}: {
  title: string;
  sub: string;
  icon: IconName;
  primary?: boolean;
  onPress: () => void;
  testID: string;
}) {
  const { c } = useTheme();
  const fg = primary ? c.onAccent : c.text;
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={`${title}. ${sub}`}
      onPress={onPress}
      style={({ pressed }) => ({
        flex: 1,
        minWidth: 140,
        minHeight: primary ? 88 : 112,
        borderRadius: radius.md,
        padding: space.lg,
        gap: space.sm,
        justifyContent: 'space-between',
        backgroundColor: primary ? c.accent : c.surface,
        borderWidth: 1,
        borderColor: primary ? c.accent : c.hairline,
        transform: [{ scale: pressed ? 0.98 : 1 }],
      })}>
      <Row gap={space.sm} style={{ flexWrap: 'nowrap' }}>
        <View
          style={{
            width: 36,
            height: 36,
            borderRadius: radius.sm,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: primary ? c.accentDisplay : c.accentSoft,
          }}>
          <Icon name={icon} color={primary ? c.onAccent : c.accent} size={20} />
        </View>
        <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
          <T v="title" style={{ color: fg }}>
            {title}
          </T>
          <T v="small" style={{ color: fg }} tone={primary ? 'onAccent' : 'muted'}>
            {sub}
          </T>
        </View>
      </Row>
    </Pressable>
  );
}
