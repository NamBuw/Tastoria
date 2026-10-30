import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { FoodStory, SLOGAN, TrayMark } from '@/components/Brand';
import { fmtG, FreshBadge, Icon, SLOT_LABEL, Tray } from '@/components/domain';
import { Button, Card, Empty, ErrorBox, Loading, Rise, Row, Screen, Section, Skeleton, T } from '@/components/ui';
import { getProgress } from '@/lib/onboarding';
import { currentMeal, MEAL_LABEL, useLatestPlan, useLots, useProfile } from '@/lib/queries';
import { font, radius, space, TOUCH, useTheme } from '@/theme';

export default function Home() {
  const router = useRouter();
  const { c } = useTheme();
  const { user } = useSession();
  const profile = useProfile();
  const lots = useLots();
  const meal = currentMeal();
  const plan = useLatestPlan(meal);
  const [checked, setChecked] = useState(false);

  // first login without a finished "Hồ sơ 60 giây" → onboarding (UC09 trigger)
  useEffect(() => {
    if (!user || !profile.data || checked) return;
    const p = profile.data;
    const started = p.updated_at !== null || p.allergen_codes.length > 0 || p.favorite_recipe_ids.length > 0 || p.diet_code !== null;
    getProgress(user.id).then((pr) => {
      setChecked(true);
      if (!pr.done && !started) router.replace(pr.consent ? '/onboarding/ho-so' : '/onboarding');
    });
  }, [user, profile.data, checked, router]);

  const soon = (lots.data?.items ?? []).filter((l) => ['dung_ngay', 'dung_som', 'kiem_tra'].includes(l.freshness_label));

  const active = plan.data ? plan.data.items.filter((i) => i.status === 'active') : [];
  const today = new Date();
  const dateLine = `${['Chủ nhật', 'Thứ hai', 'Thứ ba', 'Thứ tư', 'Thứ năm', 'Thứ sáu', 'Thứ bảy'][today.getDay()]}, ${today.getDate()}/${today.getMonth() + 1}`;

  return (
    <Screen testID="screen-home">
      <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap', marginTop: space.sm }}>
        <Row style={{ flexWrap: 'nowrap', flexShrink: 1 }} gap={space.sm}>
          <TrayMark size={32} />
          <View style={{ flexShrink: 1 }}>
            <T v="title" style={{ fontFamily: font.bold }}>Tastoria</T>
            <T v="small" tone="accent">{SLOGAN}</T>
          </View>
        </Row>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Cài đặt"
          testID="open-settings"
          onPress={() => router.push('/cai-dat')}
          style={({ pressed }) => ({
            width: TOUCH,
            height: TOUCH,
            borderRadius: TOUCH / 2,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: pressed ? c.surfaceAlt : c.surface,
            borderWidth: 1,
            borderColor: c.hairline,
          })}>
          <Icon name="gear" color={c.text} size={22} />
        </Pressable>
      </Row>

      <FoodStory compact />

      <View style={{ gap: 2 }}>
        <T tone="muted">{dateLine}</T>
        <T v="huge" accessibilityRole="header">
          {MEAL_LABEL[meal]} hôm nay
        </T>
      </View>

      <View>
        {plan.isLoading ? <Skeleton height={236} r={radius.lg} /> : null}
        {plan.error ? <ErrorBox message={errorText(plan.error)} onRetry={() => plan.refetch()} /> : null}
        {plan.data ? (
          <Rise>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Mở mâm ${MEAL_LABEL[meal].toLowerCase()}: ${active.map((i) => i.recipe_name_vi).join(', ')}`}
              onPress={() => router.push('/mam')}
              testID="home-latest-plan">
              {({ pressed }) => (
                <Card style={{ gap: space.lg, padding: space.lg, transform: [{ scale: pressed ? 0.99 : 1 }] }}>
                  <Row style={{ flexWrap: 'nowrap' }} gap={space.lg}>
                    <Tray items={active} size={132} compact />
                    <View style={{ flex: 1, gap: space.sm }}>
                      {active.map((i) => (
                        <View key={i.id}>
                          <T v="small" tone="accent" style={{ fontFamily: font.semibold }}>
                            {SLOT_LABEL[i.slot]}
                          </T>
                          <T v="label" numberOfLines={2}>
                            {i.recipe_name_vi}
                          </T>
                        </View>
                      ))}
                    </View>
                  </Row>
                  <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                    <T v="small" tone="muted">
                      {plan.data!.status === 'accepted' ? 'Đã nhận mâm' : 'Đang đề xuất'}, {plan.data!.persons} người
                    </T>
                    <T v="label" tone="accent">
                      Xem mâm
                    </T>
                  </Row>
                </Card>
              )}
            </Pressable>
          </Rise>
        ) : plan.data === null ? (
          <Empty
            title={`Chưa có mâm cho ${MEAL_LABEL[meal].toLowerCase()}`}
            body="Tastoria ghép một mặn, một rau, một canh từ đồ đang có trong kho."
            action={<Button label="Ra mâm từ đồ đang có" testID="home-make-plan" onPress={() => router.push('/mam')} />}
          />
        ) : null}
      </View>

      <Row style={{ flexWrap: 'nowrap', alignItems: 'stretch' }} gap={space.md}>
        <ScanTile
          primary
          title="Chụp tủ lạnh"
          sub="1–2 ảnh, nhận ra đồ đang có"
          icon="camera"
          testID="home-scan-fridge"
          onPress={() => router.push({ pathname: '/quet', params: { mode: 'fridge' } })}
        />
        <ScanTile
          title="Chụp đồ vừa mua"
          sub="Ghi ngày mua là hôm nay"
          icon="bag"
          testID="home-scan-haul"
          onPress={() => router.push({ pathname: '/quet', params: { mode: 'haul' } })}
        />
      </Row>

      <Section
        title="Tươi ngon, dùng đúng lúc"
        right={<Button kind="ghost" label="Xem kho" onPress={() => router.push('/kho')} style={{ paddingHorizontal: space.sm }} />}>
        {lots.isLoading ? <Loading rows={1} /> : null}
        {lots.error ? <ErrorBox message={errorText(lots.error)} onRetry={() => lots.refetch()} /> : null}
        {lots.data && soon.length === 0 ? (
          <T tone="muted">{lots.data.items.length ? 'Chưa có đồ nào cần dùng gấp.' : 'Kho đang trống. Chụp tủ lạnh hoặc thêm đồ trong Kho.'}</T>
        ) : null}
        {soon.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm, paddingRight: space.lg }}>
            {soon.slice(0, 10).map((l) => (
              <View
                key={l.id}
                style={{
                  backgroundColor: c.surface,
                  borderColor: c.hairline,
                  borderLeftColor: c.fresh[l.freshness_label],
                  borderLeftWidth: 4,
                  borderWidth: 1,
                  borderRadius: radius.md,
                  padding: space.md,
                  width: 168,
                  gap: 6,
                }}>
                <T v="label" numberOfLines={1}>{l.ingredient_name_vi}</T>
                <T v="small" tone="muted">
                  còn {fmtG(l.balance_g_min, l.balance_g_max)}
                </T>
                <FreshBadge value={l.freshness_label} small />
              </View>
            ))}
          </ScrollView>
        ) : null}
      </Section>
      <Card style={{ backgroundColor: c.herbSoft, borderColor: c.herbSoft }}>
        <Row gap={space.md}>
          <Icon name="book" color={c.herb} size={28} />
          <T v="h2" tone="herb">Chuyện bếp của bạn</T>
        </Row>
        <T>Mỗi mâm cơm đã nấu là một trang trong nhật ký. Cùng nhìn lại những bữa ăn của tuần này.</T>
        <Button kind="ghost" label="Mở nhật ký nấu ăn →" onPress={() => router.push('/nhat-ky')} />
      </Card>
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
        minHeight: 128,
        borderRadius: radius.lg,
        padding: space.lg,
        gap: space.sm,
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
          borderRadius: 20,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: primary ? 'rgba(255,255,255,0.18)' : c.accentSoft,
        }}>
        <Icon name={icon} color={primary ? c.onAccent : c.accent} size={22} />
      </View>
      <FoodStory compact />

      <View style={{ gap: 2 }}>
        <T v="title" style={{ color: fg }}>{title}</T>
        <T v="small" style={{ color: fg, opacity: primary ? 0.92 : 1 }} tone={primary ? 'onAccent' : 'muted'}>
          {sub}
        </T>
      </View>
    </Pressable>
  );
}
