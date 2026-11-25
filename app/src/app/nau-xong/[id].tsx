import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { View } from 'react-native';

import { api, ApiError, call, isCode } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { fmtG, SLOT_LABEL } from '@/components/domain';
import { Button, Card, ErrorBox, Loading, Notice, Radio, Row, Screen, Section, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { fmtLeft, useCookSession, useNow } from '@/lib/cooking';
import { goTab } from '@/lib/nav';
import { clearCompleteOutcome, enqueueComplete, flush, getCompleteOutcome, onOutboxChange, type CompleteOutcome } from '@/lib/outbox';
import { space } from '@/theme';

/** Nấu xong một chạm (UC20) + hoàn tác trong 10 phút (UC21). */
export default function Finished() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useSession();
  const router = useRouter();
  const qc = useQueryClient();
  const session = useCookSession(id);
  const catalog = useCatalog();
  const plan = useQuery({
    queryKey: ['plan', session.data?.meal_plan_id],
    queryFn: () => call(api.GET('/meal-plans/{id}', { params: { path: { id: session.data!.meal_plan_id } } })),
    enabled: !!session.data,
  });
  const [liked, setLiked] = useState<Record<string, boolean | null>>({});
  const [outcome, setOutcome] = useState<CompleteOutcome | null>(null);
  const [confirmUndo, setConfirmUndo] = useState(false);
  const now = useNow();

  const readOutcome = useCallback(() => getCompleteOutcome(id, user?.id).then(setOutcome), [id, user?.id]);
  useEffect(() => {
    readOutcome();
    return onOutboxChange(() => {
      readOutcome();
    });
  }, [readOutcome]);
  useEffect(() => {
    if (outcome?.state === 'done') {
      qc.invalidateQueries({ queryKey: ['lots'] });
      qc.invalidateQueries({ queryKey: ['plan'] });
      qc.invalidateQueries({ queryKey: ['journal'] });
    }
  }, [outcome?.state, qc]);

  const finish = async () => {
    const feedback = Object.entries(liked)
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([meal_plan_item_id, v]) => ({ meal_plan_item_id, liked: v }));
    await enqueueComplete(id, { completed_at: new Date().toISOString(), feedback }, user?.id);
    await readOutcome();
  };

  const undo = useMutation({
    mutationFn: () => call(api.POST('/cook-sessions/{id}/undo', { params: { path: { id } } })),
    onSuccess: async () => {
      await clearCompleteOutcome(id, user?.id);
      setOutcome(null);
      qc.invalidateQueries({ queryKey: ['lots'] });
      qc.invalidateQueries({ queryKey: ['plan'] });
      qc.invalidateQueries({ queryKey: ['journal'] });
      qc.invalidateQueries({ queryKey: ['cook', id] });
      goTab('/mam');
    },
  });

  if (session.isLoading) return <Screen><Loading /></Screen>;
  const s = session.data;
  const items = plan.data?.items.filter((i) => i.status === 'active') ?? [];
  const result = outcome?.state === 'done' ? outcome.result : null;
  const deadline = result?.cook_session.undo_deadline ?? (s?.status === 'completed' ? s.undo_deadline : null);
  const left = deadline ? new Date(deadline).getTime() - now : 0;
  const completed = !!result || s?.status === 'completed';

  if (s?.status === 'reverted') {
    return (
      <Screen testID="screen-reverted" variant="focused">
        <T v="h1" accessibilityRole="header">
          Đã hoàn tác
        </T>
        <Notice>
          <T>Bữa này đã được hoàn tác; nguyên liệu đã được trả lại Tủ lạnh.</T>
        </Notice>
        <Button label="Về Nấu ăn" onPress={() => goTab('/mam')} />
      </Screen>
    );
  }

  if (!completed) {
    return (
      <Screen
        testID="screen-finish"
        variant="focused"
        footer={
          outcome?.state === 'pending' && outcome.authRequired ? undefined : outcome?.state === 'pending' ? (
            <>
              <Notice>
                <T>Đã lưu tạm, sẽ đồng bộ khi có mạng. Tủ lạnh chỉ trừ khi máy chủ nhận được.</T>
              </Notice>
              <Button label="Gửi lại ngay" kind="secondary" onPress={() => flush(user?.id)} />
            </>
          ) : (
            <Button label="Hoàn tất &amp; trừ nguyên liệu" testID="finish-submit" onPress={finish} />
          )
        }>
        <T v="h1" accessibilityRole="header">
          Bữa nay thế nào?
        </T>
        <T tone="muted">Không bắt buộc. Đánh giá giúp lần sau gợi ý món hợp nhà bạn hơn.</T>
        {plan.isLoading ? <Loading /> : null}
        {items.map((i) => (
          <Card key={i.id}>
            <T v="label">
              {SLOT_LABEL[i.slot]}: {i.recipe_name_vi}
            </T>
            <Row>
              <Radio label="Ngon, sẽ nấu lại" selected={liked[i.id] === true} onPress={() => setLiked((x) => ({ ...x, [i.id]: true }))} />
              <Radio label="Không thích" selected={liked[i.id] === false} onPress={() => setLiked((x) => ({ ...x, [i.id]: false }))} />
              {liked[i.id] !== undefined && liked[i.id] !== null ? (
                <Button kind="ghost" label="Bỏ chọn" onPress={() => setLiked((x) => ({ ...x, [i.id]: null }))} />
              ) : null}
            </Row>
          </Card>
        ))}
        {outcome?.state === 'pending' && outcome.authRequired ? (
          <View style={{ gap: space.sm }}>
            <ErrorBox message="Phiên đăng nhập hết hạn, đăng nhập lại để đồng bộ" />
            <Button label="Đăng nhập lại" onPress={() => router.replace('/dang-nhap')} />
          </View>
        ) : outcome?.state === 'failed' ? (
          outcome.status === 401 ? (
            <View style={{ gap: space.sm }}>
              <ErrorBox message="Phiên đăng nhập hết hạn, đăng nhập lại để đồng bộ" />
              <Button label="Đăng nhập lại" onPress={() => router.replace('/dang-nhap')} />
            </View>
          ) : (
            <ErrorBox message={errorText(new ApiError(outcome.status, outcome.problem as never))} />
          )
        ) : null}
      </Screen>
    );
  }

  // summary of deductions per ingredient
  const byIng = new Map<string, { min: number; max: number; lots: number }>();
  result?.deductions.forEach((d) => {
    const cur = byIng.get(d.ingredient_id) ?? { min: 0, max: 0, lots: 0 };
    byIng.set(d.ingredient_id, { min: cur.min - d.delta_g_min, max: cur.max - d.delta_g_max, lots: cur.lots + 1 });
  });
  const ingName = (iid: string) => catalog.ingredients.get(iid)?.name_vi ?? 'Nguyên liệu';
  const undoExpired = isCode(undo.error, 'undo_window_expired');
  const canUndo = Boolean(deadline && left > 0 && !undoExpired);

  return (
    <Screen
      testID="screen-finished"
      variant="focused"
      footer={
        <>
          {canUndo ? (
            confirmUndo ? (
              <Notice tone="warn">
                <T>Hoàn tác việc trừ nguyên liệu của bữa này?</T>
                <Row>
                  <Button label="Hoàn tác" kind="danger" testID="undo-confirm" onPress={() => undo.mutate()} loading={undo.isPending} />
                  <Button label="Thôi" kind="ghost" onPress={() => setConfirmUndo(false)} />
                </Row>
              </Notice>
            ) : (
              <Button
                label={`Hoàn tác (còn ${fmtLeft(left)})`}
                kind="secondary"
                testID="undo"
                onPress={() => setConfirmUndo(true)}
              />
            )
          ) : (
            <Notice tone="warn">
              <T v="small">
                Đã quá 10 phút để hoàn tác. Bạn có thể chỉnh lại số lượng trực tiếp trong Tủ lạnh.
              </T>
              {undoExpired ? <Button label="Mở Tủ lạnh" kind="secondary" onPress={() => goTab('/kho')} /> : null}
            </Notice>
          )}
          {undo.error && !undoExpired ? <ErrorBox message={errorText(undo.error)} /> : null}
          <Button label="Xem Nhật ký" onPress={() => goTab('/nhat-ky')} />
        </>
      }>
      <T v="h1" accessibilityRole="header">
        Đã hoàn tất bữa ăn
      </T>
      <Notice tone="ok">
        <T v="title">Đã trừ khỏi Tủ lạnh</T>
        <T>Bữa ăn đã được ghi vào Nhật ký.</T>
      </Notice>
      {canUndo ? (
        <T v="small" tone="muted" tabular testID="timer-value">
          Có thể hoàn tác trong {fmtLeft(left)} nữa
        </T>
      ) : null}
      {result ? (
        <Section title="Đã dùng">
          <Card>
            {byIng.size ? (
              [...byIng.entries()].map(([iid, v]) => (
                <Row key={iid} style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                  <T style={{ flexShrink: 1 }}>{ingName(iid)}</T>
                  <T v="label" tabular>
                    {fmtG(v.min, v.max)}
                  </T>
                </Row>
              ))
            ) : (
              <T tone="muted">Không trừ nguyên liệu nào trong tủ (chỉ dùng gia vị có sẵn).</T>
            )}
          </Card>
        </Section>
      ) : (
        <T tone="muted">Bữa này đã hoàn tất trước đó.</T>
      )}
      {result?.shortfalls?.length ? (
        <Section title="Tủ thiếu so với công thức">
          <View style={{ gap: space.xs }}>
            {result.shortfalls.map((sf) => (
              <T key={sf.ingredient_id} tabular>
                {ingName(sf.ingredient_id)}: thiếu khoảng {Math.round(sf.short_g)} g
              </T>
            ))}
          </View>
        </Section>
      ) : null}
    </Screen>
  );
}
