import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { TrayMark } from '@/components/Brand';
import { fmtG, FreshBadge, Icon, Tray } from '@/components/domain';
import { Button, Card, ErrorBox, Loading, Row, Screen, Section, T } from '@/components/ui';
import { getProgress } from '@/lib/onboarding';
import { currentMeal, MEAL_LABEL, useLatestPlan, useLots, useProfile } from '@/lib/queries';
import { radius, space, TOUCH, useTheme } from '@/theme';

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

  return (
    <Screen testID="screen-home">
      <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap', marginTop: space.md }}>
        <Row style={{ flexWrap: 'nowrap', flexShrink: 1 }} gap={space.md}>
          <TrayMark size={44} />
          <View style={{ flexShrink: 1 }}>
            <T v="h1" accessibilityRole="header">
              Tastoria
            </T>
            <T tone="muted" numberOfLines={1}>
              {MEAL_LABEL[meal]} hôm nay
            </T>
          </View>
        </Row>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Cài đặt"
          testID="open-settings"
          onPress={() => router.push('/cai-dat')}
          style={{ width: TOUCH, height: TOUCH, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="gear" color={c.text} size={26} />
        </Pressable>
      </Row>

      <View style={{ gap: space.md }}>
        <Button
          big
          label="Chụp tủ lạnh"
          sub="1–2 ảnh, nhận ra đồ đang có"
          icon={<Icon name="camera" color={c.onAccent} size={30} />}
          testID="home-scan-fridge"
          onPress={() => router.push({ pathname: '/quet', params: { mode: 'fridge' } })}
        />
        <Button
          big
          kind="secondary"
          label="Chụp đồ vừa mua"
          sub="Ghi ngày mua là hôm nay"
          icon={<Icon name="bag" color={c.accent} size={30} />}
          testID="home-scan-haul"
          onPress={() => router.push({ pathname: '/quet', params: { mode: 'haul' } })}
        />
      </View>

      <Section
        title="Nên dùng sớm"
        right={<Button kind="ghost" label="Xem kho" onPress={() => router.push('/kho')} />}>
        {lots.isLoading ? <Loading /> : null}
        {lots.error ? <ErrorBox message={errorText(lots.error)} onRetry={() => lots.refetch()} /> : null}
        {lots.data && soon.length === 0 ? (
          <T tone="muted">{lots.data.items.length ? 'Chưa có đồ nào cần dùng gấp.' : 'Kho đang trống. Chụp tủ lạnh hoặc thêm đồ trong Kho.'}</T>
        ) : null}
        {soon.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: space.sm }}>
            {soon.slice(0, 10).map((l) => (
              <View
                key={l.id}
                style={{
                  backgroundColor: c.surface,
                  borderColor: c.surfaceAlt,
                  borderWidth: 1,
                  borderRadius: radius.md,
                  padding: space.md,
                  minWidth: 150,
                  gap: 4,
                }}>
                <T v="label">{l.ingredient_name_vi}</T>
                <T v="small" tone="muted">
                  còn {fmtG(l.balance_g_min, l.balance_g_max)}
                </T>
                <FreshBadge value={l.freshness_label} small />
              </View>
            ))}
          </ScrollView>
        ) : null}
      </Section>

      <Section title={`Mâm ${MEAL_LABEL[meal].toLowerCase()}`}>
        {plan.isLoading ? <Loading /> : null}
        {plan.error ? <ErrorBox message={errorText(plan.error)} onRetry={() => plan.refetch()} /> : null}
        {plan.data ? (
          <Pressable accessibilityRole="button" onPress={() => router.push('/mam')} testID="home-latest-plan">
            <Card style={{ flexDirection: 'row', alignItems: 'center', gap: space.lg }}>
              <Tray items={plan.data.items.filter((i) => i.status === 'active')} size={110} compact />
              <View style={{ flex: 1, gap: 4 }}>
                {plan.data.items
                  .filter((i) => i.status === 'active')
                  .map((i) => (
                    <T key={i.id}>{i.recipe_name_vi}</T>
                  ))}
                <T v="small" tone="muted">
                  {plan.data.status === 'accepted' ? 'Đã nhận mâm' : 'Đang đề xuất'} · {plan.data.persons} người
                </T>
              </View>
            </Card>
          </Pressable>
        ) : plan.data === null ? (
          <Card>
            <T tone="muted">Chưa có mâm cho {MEAL_LABEL[meal].toLowerCase()}.</T>
            <Button label="Ra mâm từ đồ đang có" testID="home-make-plan" onPress={() => router.push('/mam')} />
          </Card>
        ) : null}
      </Section>
    </Screen>
  );
}
