import { Image } from 'expo-image';
import { type Href, useNavigation, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { AppState, Pressable, ScrollView, View } from 'react-native';

import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { BotanicalCornerMark, FOOD_PHOTOS, recipePhotoFor, SLOGAN, StarAniseDivider, VermilionSeal, Wordmark } from '@/components/Brand';
import { fmtG, FreshBadge, Icon, SLOT_LABEL } from '@/components/domain';
import { Button, BroadsheetLedgerFrame, Card, ErrorBox, Loading, Rise, Row, Screen, Section, Skeleton, T } from '@/components/ui';
import { getProgress } from '@/lib/onboarding';
import { currentMeal, MEAL_LABEL, useLatestPlan, useLots, useProfile } from '@/lib/queries';
import { font, radius, space, TOUCH, useLayout, useTheme } from '@/theme';

const SLOT_ORDER = { man: 0, rau: 1, canh: 2 } as const;

export default function Home() {
  const router = useRouter();
  const nav = useNavigation() as { addListener?: (ev: string, cb: () => void) => () => void };
  const { c } = useTheme();
  const { isDesktop, isMobile, isTinyPhone } = useLayout();
  const { user } = useSession();
  const profile = useProfile();
  const lots = useLots();
  const [nowTs, setNowTs] = useState(() => Date.now());
  const today = new Date(nowTs);
  const meal = currentMeal(today);
  const plan = useLatestPlan(meal);
  const [checked, setChecked] = useState(false);

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

  // first login without a finished "Hồ sơ 60 giây" -> onboarding (UC09 trigger)
  useEffect(() => {
    if (!user || !profile.data || checked) return;
    const p = profile.data;
    const started = p.updated_at !== null || p.allergen_codes.length > 0 || p.favorite_recipe_ids.length > 0 || p.diet_code !== null;
    getProgress(user.id).then((pr) => {
      setChecked(true);
      if (!pr.done && !started) router.replace(pr.consent ? '/onboarding/ho-so' : '/onboarding');
    });
  }, [user, profile.data, checked, router]);

  const allLots = lots.data?.items ?? [];
  const soon = allLots.filter((l) => ['dung_ngay', 'dung_som', 'kiem_tra'].includes(l.freshness_label));
  const isStaff = user?.role === 'admin' || user?.role === 'ml_operator';
  const active = plan.data ? plan.data.items.filter((i) => i.status === 'active') : [];
  const ordered = [...active].sort((a, b) => SLOT_ORDER[a.slot] - SLOT_ORDER[b.slot]);
  const dateLine = `${['Chủ nhật', 'Thứ hai', 'Thứ ba', 'Thứ tư', 'Thứ năm', 'Thứ sáu', 'Thứ bảy'][today.getDay()]}, ${today.getDate()} tháng ${today.getMonth() + 1}`;

  const mealHero = (
    <View>
      {plan.isLoading ? <Skeleton height={240} r={radius.lg} /> : null}
      {plan.error ? <ErrorBox message={errorText(plan.error)} onRetry={() => plan.refetch()} /> : null}
      {plan.data ? (
        <Rise>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Mở mâm ${MEAL_LABEL[meal].toLowerCase()}: ${ordered.map((i) => i.recipe_name_vi).join(', ')}`}
            onPress={() => router.push('/mam')}
            testID="home-latest-plan">
            {({ pressed }) => (
              <BroadsheetLedgerFrame
                title={`${plan.data!.status === 'accepted' ? 'Mâm đã chốt' : 'Mâm đề xuất'}, ${plan.data!.persons} người`}
                rightText="Mở mâm cơm →"
                accentTone="herb"
                style={{ transform: [{ scale: pressed ? 0.99 : 1 }] }}
                innerStyle={{ padding: 0, gap: 0 }}>
                <View style={{ paddingHorizontal: space.lg, paddingVertical: space.xs, backgroundColor: c.surfaceAlt }}>
                  <StarAniseDivider label="Mâm cơm hôm nay: Mặn, Rau, Canh" />
                </View>
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
                              style={{ width: 56, height: 56, borderRadius: radius.sm, backgroundColor: c.surfaceAlt, borderWidth: 1, borderColor: c.hairline }}
                              accessibilityLabel={i.recipe_name_vi}
                            />
                          ) : (
                            <View
                              style={{
                                width: 56,
                                height: 56,
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
                            <T v="title" style={{ fontFamily: font.displaySemibold }} numberOfLines={2}>
                              {i.recipe_name_vi}
                            </T>
                          </View>
                        </Row>
                        {i.kcal_per_person != null ? (
                          <View style={{ backgroundColor: c.surfaceAlt, borderWidth: 1, borderColor: c.hairline, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.sm }}>
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
                        : 'Cơm trắng ăn kèm'}
                    </T>
                  </Row>
                </View>
              </BroadsheetLedgerFrame>
            )}
          </Pressable>
        </Rise>
      ) : plan.data === null ? (
        <BroadsheetLedgerFrame
          title={`Chưa có mâm cho ${MEAL_LABEL[meal].toLowerCase()}`}
          accentTone="herb"
          innerStyle={{ padding: 0, gap: 0, overflow: 'hidden' }}>
          <Image
            source={FOOD_PHOTOS.bunDau}
            contentFit="cover"
            style={{ width: '100%', height: isDesktop ? 210 : 168 }}
            accessibilityLabel="Mâm cơm đậu rán, thịt luộc, rau thơm và dưa leo"
          />
          <View style={{ padding: space.lg, gap: space.md }}>
            <T tone="muted">
              Kiểm tra đồ còn trong tủ, ưu tiên món sắp hết hạn rồi ghép sẵn mâm 3 món mặn, rau, canh vừa miệng cả nhà.
            </T>
            <Row gap={space.sm}>
              <Button label="Ra mâm từ đồ đang có" testID="home-make-plan" onPress={() => router.push('/mam')} />
              <Button
                kind="secondary"
                label="Quét tủ lạnh trước"
                onPress={() => router.push({ pathname: '/quet', params: { mode: 'fridge' } })}
              />
            </Row>
          </View>
        </BroadsheetLedgerFrame>
      ) : null}
    </View>
  );

  const scanTiles = (
    <Row style={{ flexWrap: isTinyPhone ? 'wrap' : 'nowrap', alignItems: 'stretch' }} gap={space.md}>
      <ScanTile
        primary
        title="Chụp tủ lạnh"
        sub="1 đến 2 ảnh, tự điền tên và số lượng"
        icon="camera"
        testID="home-scan-fridge"
        onPress={() => router.push({ pathname: '/quet', params: { mode: 'fridge' } })}
      />
      <ScanTile
        title="Chụp đồ vừa mua"
        sub="Tự động ghi ngày mua hôm nay"
        icon="bag"
        testID="home-scan-haul"
        onPress={() => router.push({ pathname: '/quet', params: { mode: 'haul' } })}
      />
    </Row>
  );

  const urgentSection = (
    <Section
      title="Nguyên liệu cần ưu tiên"
      right={<Button kind="ghost" label="Mở kho bếp" onPress={() => router.push('/kho')} style={{ paddingHorizontal: space.sm }} />}>
      {lots.isLoading ? <Loading rows={1} /> : null}
      {lots.error ? <ErrorBox message={errorText(lots.error)} onRetry={() => lots.refetch()} /> : null}
      {lots.data && soon.length === 0 ? (
        <View style={{ backgroundColor: c.surfaceAlt, borderRadius: radius.lg, borderWidth: 1, borderColor: c.hairline, padding: space.lg }}>
          <T tone="muted">
            {allLots.length
              ? `Cả ${allLots.length} lô trong kho đều đang tươi mới, chưa có nguyên liệu nào cần dùng gấp.`
              : 'Kho bếp đang trống. Hãy chụp ảnh tủ lạnh hoặc thêm nguyên liệu để bắt đầu lên mâm.'}
          </T>
        </View>
      ) : null}
      {soon.length ? (
        isDesktop ? (
          <View style={{ gap: space.md }}>
            {Array.from({ length: Math.ceil(soon.slice(0, 6).length / 2) }, (_, rowIdx) => {
              const pair = soon.slice(0, 6).slice(rowIdx * 2, rowIdx * 2 + 2);
              return (
                <View key={`soon-row-${rowIdx}`} style={{ flexDirection: 'row', gap: space.md }}>
                  {pair.map((l) => (
                    <Pressable
                      key={l.id}
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
                          {l.ingredient_name_vi}
                        </T>
                        <T v="small" tone="muted" tabular>
                          {fmtG(l.balance_g_min, l.balance_g_max)}
                        </T>
                      </Row>
                      <FreshBadge value={l.freshness_label} small />
                    </Pressable>
                  ))}
                  {pair.length === 1 ? <View style={{ flex: 1, flexBasis: 0, minWidth: 0 }} pointerEvents="none" /> : null}
                </View>
              );
            })}
          </View>
        ) : (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm, paddingRight: space.lg }}>
            {soon.slice(0, 10).map((l) => (
              <Pressable
                key={l.id}
                accessibilityRole="button"
                onPress={() => router.push('/kho')}
                style={{
                  backgroundColor: c.surface,
                  borderColor: c.hairline,
                  borderWidth: 1,
                  borderRadius: radius.md,
                  padding: space.md,
                  width: 176,
                  gap: 8,
                }}>
                <T v="title" numberOfLines={1}>
                  {l.ingredient_name_vi}
                </T>
                <T v="small" tone="muted" tabular>
                  Còn {fmtG(l.balance_g_min, l.balance_g_max)}
                </T>
                <FreshBadge value={l.freshness_label} small />
              </Pressable>
            ))}
          </ScrollView>
        )
      ) : null}
    </Section>
  );

  const exploreShortcut = (
    <Card style={{ gap: space.md, position: 'relative', overflow: 'hidden' }}>
      <BotanicalCornerMark />
      <View style={{ gap: 4 }}>
        <T v="title" style={{ fontFamily: font.displaySemibold }}>Món cơm nhà quen thuộc</T>
        <T v="body" tone="muted">
          Tìm món theo nguyên liệu đang có sẵn, thời gian nấu và thành phần dinh dưỡng từng khẩu phần.
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
        <View style={{ gap: space.sm, marginTop: space.xs }}>
          <View style={{ borderBottomWidth: 1.5, borderBottomColor: c.border, paddingBottom: space.sm, gap: space.xs }}>
            <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap', alignItems: 'center' }} gap={space.sm}>
              <Wordmark size="md" masthead />
              <Row gap={space.xs} style={{ flexWrap: 'nowrap' }}>
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
                    borderColor: c.border,
                  })}>
                  <Icon name="gear" color={c.text} size={20} />
                </Pressable>
              </Row>
            </Row>
            <View
              style={{
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: space.sm,
                backgroundColor: c.border,
                paddingHorizontal: space.sm,
                paddingVertical: 3,
                borderRadius: radius.sm,
              }}>
              <T v="small" style={{ color: c.surface, fontFamily: font.medium, fontSize: 11, lineHeight: 15 }}>
                {SLOGAN.toUpperCase()}
              </T>
              <VermilionSeal label="BẾP VIỆT" />
            </View>
          </View>
          <View style={{ height: 1, backgroundColor: c.hairline, marginTop: -6 }} />
          {isStaff ? (
            <Row gap={space.sm}>
              <Button
                kind="secondary"
                compact
                label="Quản trị"
                testID="home-open-admin"
                icon={<Icon name="shield" size={16} color={c.info} />}
                onPress={() => router.push('/quan-tri' as Href)}
              />
            </Row>
          ) : null}
        </View>
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
              <View style={{ backgroundColor: c.surface, borderColor: c.border, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: space.md, paddingVertical: 8, maxWidth: '100%', flexShrink: 1 }}>
                <T v="small" tabular>
                  Kho: <T v="label" tabular>{allLots.length} lô</T>, cần dùng sớm: <T v="label" tone="accent" tabular>{soon.length}</T>
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
              {mealHero}
              {urgentSection}
            </View>
            <View style={{ flex: 5, minWidth: 0, gap: space.xl }}>
              {scanTiles}
              {exploreShortcut}
            </View>
          </View>
        </View>
      ) : (
        <>
          <View style={{ gap: 4 }}>
            <T v="small" tone="muted">
              {dateLine}
            </T>
            <T v="huge" accessibilityRole="header">
              {MEAL_LABEL[meal]} hôm nay
            </T>
          </View>
          {mealHero}
          {scanTiles}
          {urgentSection}
        </>
      )}
    </Screen>
  );
}

function ScanTile({
  title,
  sub,
  icon,
  primary,
  onPress,
  testID,
}: {
  title: string;
  sub: string;
  icon: 'camera' | 'bag';
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
        minHeight: 124,
        borderRadius: radius.md,
        padding: space.lg,
        gap: space.md,
        justifyContent: 'space-between',
        backgroundColor: primary ? c.accent : c.surface,
        borderWidth: 1,
        borderColor: primary ? c.accent : c.hairline,
        transform: [{ scale: pressed ? 0.98 : 1 }],
      })}>
      <View
        style={{
          width: 40,
          height: 40,
          borderRadius: radius.sm,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: primary ? c.accentDisplay : c.accentSoft,
        }}>
        <Icon name={icon} color={primary ? c.onAccent : c.accent} size={20} />
      </View>

      <View style={{ gap: 2 }}>
        <T v="title" style={{ color: fg }}>
          {title}
        </T>
        <T v="small" style={{ color: fg }} tone={primary ? 'onAccent' : 'muted'}>
          {sub}
        </T>
      </View>
    </Pressable>
  );
}
