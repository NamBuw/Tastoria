import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { View } from 'react-native';

import { api, ApiError, call } from '@/api/client';
import { goTab } from '@/lib/nav';
import { errorText } from '@/api/errors';
import { fmtG, SLOT_LABEL } from '@/components/domain';
import { Button, Card, ErrorBox, Loading, Notice, Radio, Row, Screen, Section, T } from '@/components/ui';
import { useCatalog } from '@/lib/catalog';
import { fmtLeft, useCookSession, useNow } from '@/lib/cooking';
import { enqueueComplete, flush, getCompleteOutcome, onOutboxChange, type CompleteOutcome } from '@/lib/outbox';
import { space } from '@/theme';

/** Nấu xong một chạm (UC20) + hoàn tác trong 10 phút (UC21). */
export default function Finished() {
  const { id } = useLocalSearchParams<{ id: string }>();
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

  const readOutcome = useCallback(() => getCompleteOutcome(id).then(setOutcome), [id]);
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
    await enqueueComplete(id, { completed_at: new Date().toISOString(), feedback });
    await readOutcome();
  };

  const undo = useMutation({
    mutationFn: () => call(api.POST('/cook-sessions/{id}/undo', { params: { path: { id } } })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['lots'] });
      qc.invalidateQueries({ queryKey: ['plan'] });
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

  if (s?.status === 'reverted' && !result) {
    return (
      <Screen>
        <Notice>
          <T>Bữa này đã được hoàn tác; kho đã được trả lại.</T>
        </Notice>
        <Button label="Về Mâm cơm hôm nay" onPress={() => goTab('/mam')} />
      </Screen>
    );
  }

  if (!completed) {
    return (
      <Screen
        testID="screen-finish"
        footer={
          outcome?.state === 'pending' ? (
            <>
              <Notice>
                <T>Đã ghi, sẽ đồng bộ khi có mạng. Kho chỉ bị trừ khi máy chủ nhận được.</T>
              </Notice>
              <Button label="Gửi lại ngay" kind="secondary" onPress={() => flush()} />
            </>
          ) : (
            <Button label="Nấu xong, trừ kho" testID="finish-submit" onPress={finish} />
          )
        }>
        <T v="h2" accessibilityRole="header">
          Bữa nay thế nào?
        </T>
        <T tone="muted">Không bắt buộc. Chấm từng món giúp lần sau ghép mâm hợp gu hơn (chỉ lưu khi bạn đã đồng ý cá nhân hoá).</T>
        {plan.isLoading ? <Loading /> : null}
        {items.map((i) => (
          <Card key={i.id}>
            <T v="label">
              {SLOT_LABEL[i.slot]}: {i.recipe_name_vi}
            </T>
            <Row>
              <Radio label="Hợp gu" selected={liked[i.id] === true} onPress={() => setLiked((x) => ({ ...x, [i.id]: true }))} />
              <Radio label="Không hợp" selected={liked[i.id] === false} onPress={() => setLiked((x) => ({ ...x, [i.id]: false }))} />
              {liked[i.id] !== undefined && liked[i.id] !== null ? (
                <Button kind="ghost" label="Bỏ chấm" onPress={() => setLiked((x) => ({ ...x, [i.id]: null }))} />
              ) : null}
            </Row>
          </Card>
        ))}
        {outcome?.state === 'failed' ? (
          <ErrorBox message={errorText(new ApiError(outcome.status, outcome.problem as never))} />
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

  return (
    <Screen
      testID="screen-finished"
      footer={
        <>
          {deadline && left > 0 ? (
            confirmUndo ? (
              <Notice tone="warn">
                <T>Hoàn tác trừ kho của bữa này?</T>
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
            <T v="small" tone="muted">
              Đã quá 10 phút để hoàn tác. Sửa từng lô trong Kho nếu trừ sai.
            </T>
          )}
          {undo.error ? <ErrorBox message={errorText(undo.error)} /> : null}
          <Button label="Xem nhật ký tuần" onPress={() => goTab('/nhat-ky')} />
        </>
      }>
      <Notice tone="ok">
        <T v="title">Đã trừ khỏi kho</T>
        <T>Mâm đã ghi vào nhật ký.</T>
      </Notice>
      {result ? (
        <Section title="Đã dùng">
          <Card>
            {byIng.size ? (
              [...byIng.entries()].map(([iid, v]) => (
                <Row key={iid} style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                  <T style={{ flexShrink: 1 }}>{ingName(iid)}</T>
                  <T v="label">
                    {fmtG(v.min, v.max)}
                    {v.lots > 1 ? ` · ${v.lots} lô` : ''}
                  </T>
                </Row>
              ))
            ) : (
              <T tone="muted">Không trừ lô nào (mâm chỉ dùng gia vị không theo dõi trong kho).</T>
            )}
          </Card>
        </Section>
      ) : (
        <T tone="muted">Bữa này đã hoàn tất trước đó.</T>
      )}
      {result?.shortfalls?.length ? (
        <Section title="Kho thiếu so với công thức">
          <View style={{ gap: space.xs }}>
            {result.shortfalls.map((sf) => (
              <T key={sf.ingredient_id}>
                {ingName(sf.ingredient_id)}: thiếu khoảng {Math.round(sf.short_g)} g
              </T>
            ))}
          </View>
        </Section>
      ) : null}
    </Screen>
  );
}
