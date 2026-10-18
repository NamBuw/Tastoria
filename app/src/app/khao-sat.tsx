import AsyncStorage from '@react-native-async-storage/async-storage';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, View } from 'react-native';

import { api, call, isCode, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { BrandHeader } from '@/components/Brand';
import { SLOT_LABEL } from '@/components/domain';
import { Button, Card, Checkbox, Chip, ErrorBox, Field, LinkButton, Loading, Notice, Row, Screen, Section, T } from '@/components/ui';
import { radius, space, TOUCH, useTheme } from '@/theme';

const KEY = 'tastoria.survey.v1';
type Saved = { id: string; token: string };

/** Khảo sát gu món ăn (UC23): public, no account; rate 1–5 or "chưa ăn bao giờ", then up to 5 favourites. */
export default function Survey() {
  const [saved, setSaved] = useState<Saved | null | undefined>(undefined);
  const [notOpen, setNotOpen] = useState(false);
  const [thanks, setThanks] = useState(false);
  useEffect(() => {
    AsyncStorage.getItem(KEY)
      .then((raw) => setSaved(raw ? (JSON.parse(raw) as Saved) : null))
      .catch(() => setSaved(null));
  }, []);
  const store = async (s: Saved | null) => {
    setSaved(s);
    if (s) await AsyncStorage.setItem(KEY, JSON.stringify(s)).catch(() => {});
    else await AsyncStorage.removeItem(KEY).catch(() => {});
  };

  if (saved === undefined) return <Screen><Loading /></Screen>;
  if (notOpen) {
    return (
      <Screen testID="screen-survey-closed">
        <BrandHeader subtitle="Khảo sát gu món ăn" />
        <Notice tone="warn">
          <T v="title">Khảo sát chưa mở</T>
          <T>Hiện không có đợt khảo sát nào đang nhận trả lời. Cảm ơn bạn đã ghé; hãy quay lại khi nhóm gửi đường dẫn mới.</T>
        </Notice>
      </Screen>
    );
  }
  if (thanks) {
    return (
      <Screen testID="screen-survey-thanks">
        <BrandHeader subtitle="Khảo sát gu món ăn" />
        <Notice tone="ok">
          <T v="title">Đã nhận phiếu. Cảm ơn bạn.</T>
          <T>Câu trả lời được dùng để huấn luyện phần xếp hạng gu món của Tastoria.</T>
        </Notice>
      </Screen>
    );
  }
  return saved ? (
    <Form
      saved={saved}
      onReset={() => store(null)}
      onDone={async () => { await store(null); setThanks(true); }}
      onClosed={async () => { await store(null); setNotOpen(true); }}
    />
  ) : (
    <Start onStarted={store} onNotOpen={() => setNotOpen(true)} />
  );
}

function Start({ onStarted, onNotOpen }: { onStarted: (s: Saved) => void; onNotOpen: () => void }) {
  const [agree, setAgree] = useState(false);
  const [open, setOpen] = useState(false);
  // ?kenh=qr on the link printed as a QR code; anything else counts as a shared link (survey_respondents.channel)
  const { kenh } = useLocalSearchParams<{ kenh?: string }>();
  const channel = kenh === 'qr' ? 'qr' : 'link';
  const policy = useQuery({
    queryKey: ['policy', 'survey'],
    queryFn: () => call(api.GET('/policies/{purpose}/current', { params: { path: { purpose: 'survey' } } })),
  });
  const start = useMutation({
    mutationFn: () =>
      call(api.POST('/survey/respondents', { body: { policy_version_id: policy.data!.id, consent: true, channel } })),
    onSuccess: (r) => onStarted({ id: r.respondent.id, token: r.respondent_token }),
    onError: (e) => {
      // 409 survey_closed = no open form; 404 is not in the contract for this call = survey module not deployed here
      if (isCode(e, 'survey_closed') || isCode(e, 'not_found')) onNotOpen();
      if (isCode(e, 'policy_outdated')) policy.refetch();
    },
  });
  const p = policy.data;
  return (
    <Screen testID="screen-survey-start" footer={<Button label="Bắt đầu" testID="survey-start" disabled={!agree || !p} loading={start.isPending} onPress={() => start.mutate()} />}>
      <BrandHeader subtitle="Khảo sát gu món ăn" />
      <T>
        Phiếu gồm khoảng 45 món cơm nhà. Với mỗi món, chọn điểm từ 1 (không thích) đến 5 (rất thích), hoặc "Chưa ăn bao giờ". Mất khoảng 5
        phút. Không cần tài khoản.
      </T>
      {policy.isLoading ? <Loading /> : null}
      {policy.error ? <ErrorBox message={errorText(policy.error)} onRetry={() => policy.refetch()} /> : null}
      {p ? (
        <Card>
          <T v="label">{p.purpose.name_vi}</T>
          <T tone="muted">{p.purpose.description_vi}</T>
          <T v="small" tone="muted">
            Dữ liệu: {p.purpose.data_category} · điều khoản phiên bản {p.version}
          </T>
          <LinkButton label={open ? 'Ẩn điều khoản' : 'Đọc toàn văn điều khoản'} onPress={() => setOpen(!open)} />
          {open ? <T>{p.text_vi}</T> : null}
          <Checkbox testID="survey-consent" checked={agree} onChange={setAgree} label="Tôi đồng ý tham gia và cho dùng câu trả lời theo điều khoản trên" />
        </Card>
      ) : null}
      {start.error && !isCode(start.error, 'not_found') && !isCode(start.error, 'survey_closed') ? (
        <ErrorBox message={errorText(start.error)} />
      ) : null}
    </Screen>
  );
}

function Form({ saved, onReset, onDone, onClosed }: { saved: Saved; onReset: () => void; onDone: () => void; onClosed: () => void }) {
  const qc = useQueryClient();
  const headers = { 'X-Respondent-Token': saved.token };
  const r = useQuery({
    queryKey: ['survey', saved.id],
    queryFn: () => call(api.GET('/survey/respondents/{id}', { params: { path: { id: saved.id } }, headers })),
  });
  const [favs, setFavs] = useState<string[] | null>(null);
  const [q, setQ] = useState('');
  useEffect(() => {
    if (r.data && favs === null) setFavs(r.data.favorite_recipe_ids);
  }, [r.data, favs]);
  useEffect(() => {
    if (r.data?.completed_at) onDone(); // already sent from this browser earlier
  }, [r.data, onDone]);
  const rate = useMutation({
    mutationFn: ({ recipeId, body }: { recipeId: string; body: Schemas['SurveyRatingPut'] }) =>
      call(api.PUT('/survey/respondents/{id}/ratings/{recipeId}', { params: { path: { id: saved.id, recipeId } }, headers, body })),
    onSuccess: (res) =>
      qc.setQueryData<Schemas['SurveyRespondent']>(['survey', saved.id], (cur) =>
        cur
          ? {
              ...cur,
              assignments: cur.assignments.map((a) =>
                a.recipe_id === res.recipe_id ? { ...a, rating: res.rating, never_eaten: res.never_eaten } : a,
              ),
            }
          : cur,
      ),
    onError: (e) => {
      if (isCode(e, 'survey_closed')) onClosed();
      if (isCode(e, 'survey_already_completed')) onDone();
    },
  });
  const submit = useMutation({
    mutationFn: async () => {
      await call(api.PUT('/survey/respondents/{id}/favorites', { params: { path: { id: saved.id } }, headers, body: { recipe_ids: favs ?? [] } }));
      return call(api.POST('/survey/respondents/{id}/complete', { params: { path: { id: saved.id } }, headers }));
    },
    onSuccess: onDone,
    onError: (e) => {
      if (isCode(e, 'survey_closed')) onClosed();
      if (isCode(e, 'survey_already_completed')) onDone();
    },
  });

  if (r.isLoading) return <Screen><Loading /></Screen>;
  if (r.error) {
    return (
      <Screen>
        <ErrorBox message={errorText(r.error)} />
        <Button label="Bắt đầu phiếu mới" onPress={onReset} />
      </Screen>
    );
  }
  const items = [...(r.data?.assignments ?? [])].sort((a, b) => a.display_order - b.display_order);
  const answered = items.filter((a) => a.rating != null || a.never_eaten).length;
  const pick = (id: string) =>
    setFavs((s) => ((s ?? []).includes(id) ? (s ?? []).filter((x) => x !== id) : (s ?? []).length >= 5 ? s : [...(s ?? []), id]));

  return (
    <Screen
      testID="screen-survey-form"
      footer={
        <>
          {submit.error ? <ErrorBox message={errorText(submit.error)} /> : null}
          <Button label={`Gửi phiếu (${answered}/${items.length} món)`} testID="survey-submit" onPress={() => submit.mutate()} loading={submit.isPending} disabled={answered < items.length} />
        </>
      }>
      <T v="h2" accessibilityRole="header">
        Bạn thích các món này đến đâu?
      </T>
      <T tone="muted">1 = không thích, 5 = rất thích.</T>
      {rate.error ? <ErrorBox message={errorText(rate.error)} /> : null}
      {items.map((a) => (
        <Card key={a.recipe_id}>
          <T v="label">
            {a.name_vi} <T v="small" tone="muted">· {SLOT_LABEL[a.slot]}</T>
          </T>
          <Row gap={6}>
            {[1, 2, 3, 4, 5].map((n) => (
              <Score key={n} n={n} selected={a.rating === n} onPress={() => rate.mutate({ recipeId: a.recipe_id, body: { rating: n, never_eaten: false } })} />
            ))}
          </Row>
          <Chip label="Chưa ăn bao giờ" selected={!!a.never_eaten} onPress={() => rate.mutate({ recipeId: a.recipe_id, body: { rating: null, never_eaten: true } })} />
        </Card>
      ))}
      <Section title="5 món nhà bạn hay ăn (không bắt buộc)">
        <Field label="Tìm trong danh sách" value={q} onChangeText={setQ} />
        <Row>
          {items
            .filter((a) => !q || a.name_vi.toLowerCase().includes(q.toLowerCase()))
            .map((a) => (
              <Chip
                key={a.recipe_id}
                label={a.name_vi}
                selected={(favs ?? []).includes(a.recipe_id)}
                disabled={!(favs ?? []).includes(a.recipe_id) && (favs ?? []).length >= 5}
                onPress={() => pick(a.recipe_id)}
              />
            ))}
        </Row>
      </Section>
    </Screen>
  );
}

function Score({ n, selected, onPress }: { n: number; selected: boolean; onPress: () => void }) {
  const { c } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="radio"
      accessibilityState={{ selected, checked: selected }}
      accessibilityLabel={`${n} điểm`}
      style={{
        width: TOUCH,
        height: TOUCH,
        borderRadius: radius.md,
        borderWidth: selected ? 2 : 1,
        borderColor: selected ? c.accent : c.border,
        backgroundColor: selected ? c.accentSoft : c.surface,
        alignItems: 'center',
        justifyContent: 'center',
      }}>
      <View>
        <T v="title" style={{ color: selected ? c.accent : c.text }}>
          {n}
        </T>
      </View>
    </Pressable>
  );
}
