import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { View } from 'react-native';

import { api, call } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { Button, Card, ErrorBox, Loading, Notice, Row, Screen, T } from '@/components/ui';
import { qk } from '@/lib/queries';
import { radius, space, useTheme } from '@/theme';

/** ISO 8601 week of a date, e.g. 2026-W42. */
function isoWeek(d: Date): string {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y = t.getUTCFullYear();
  const w = Math.ceil(((t.getTime() - Date.UTC(y, 0, 1)) / 86400000 + 1) / 7);
  return `${y}-W${String(w).padStart(2, '0')}`;
}

const WD = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];

/** Nhật ký tuần (UC22): trays cooked, kcal per person vs target, urgent lots used. */
export default function Journal() {
  const { c } = useTheme();
  const { status } = useSession();
  const [offset, setOffset] = useState(0);
  const week = isoWeek(new Date(Date.now() + offset * 7 * 86400000));
  const q = useQuery({ queryKey: qk.journal(week), queryFn: () => call(api.GET('/journal', { params: { query: { week } } })), enabled: status === 'signedIn' });
  const days = q.data?.days ?? [];
  const max = Math.max(1, ...days.map((d) => Math.max(d.kcal_per_person ?? 0, d.e_target_kcal ?? 0)));
  const trays = days.reduce((s, d) => s + d.cooked_trays, 0);
  const urgent = days.reduce((s, d) => s + d.urgent_lots_used, 0);

  return (
    <Screen testID="screen-journal">
      <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
        <Button kind="ghost" label="‹ Tuần trước" onPress={() => setOffset(offset - 1)} />
        <T v="title">Tuần {week.split('-W')[1]}/{week.split('-W')[0]}</T>
        <Button kind="ghost" label="Tuần sau ›" onPress={() => setOffset(offset + 1)} disabled={offset >= 0} />
      </Row>
      {q.isLoading ? <Loading /> : null}
      {q.error ? <ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} /> : null}
      {q.data ? (
        <>
          <Row gap={space.md} style={{ flexWrap: 'nowrap' }}>
            <Card style={{ flex: 1 }}>
              <T v="huge">{trays}</T>
              <T tone="muted">mâm đã nấu</T>
            </Card>
            <Card style={{ flex: 1 }}>
              <T v="huge">{urgent}</T>
              <T tone="muted">lô sắp hỏng đã dùng kịp</T>
            </Card>
          </Row>
          {q.data.kcal_range_status === 'calibrating' ? (
            <Notice>
              <T>Số calo đang hiệu chỉnh: chưa đủ món đối chiếu với Viện Dinh dưỡng nên chỉ xem như số tham khảo.</T>
            </Notice>
          ) : null}
          <Card>
            <T v="label">Calo mỗi người theo ngày (từ mâm đã nấu)</T>
            <View style={{ gap: space.sm }}>
              {days.map((d) => {
                const date = new Date(`${d.date}T00:00:00`);
                return (
                  <View key={d.date} style={{ gap: 4 }}>
                    <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                      <T v="label">
                        {WD[date.getDay()]} {date.getDate()}/{date.getMonth() + 1}
                      </T>
                      <T tone={d.kcal_per_person == null ? 'muted' : 'text'}>
                        {d.kcal_per_person == null
                          ? 'chưa nấu'
                          : `${Math.round(d.kcal_per_person)} kcal${d.e_target_kcal ? ` / mục tiêu ${Math.round(d.e_target_kcal)}` : ''}`}
                      </T>
                    </Row>
                    <View style={{ height: 10, borderRadius: radius.pill, backgroundColor: c.surfaceAlt }}>
                      {d.kcal_per_person != null ? (
                        <View
                          style={{
                            width: `${Math.min(100, (d.kcal_per_person / max) * 100)}%`,
                            height: 10,
                            borderRadius: radius.pill,
                            backgroundColor: c.accent,
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
                            width: 3,
                            backgroundColor: c.text,
                          }}
                        />
                      ) : null}
                    </View>
                  </View>
                );
              })}
            </View>
            <T v="small" tone="muted">
              Vạch dọc là mục tiêu năng lượng máy chủ ghi cho ngày đó (nếu đã đặt). Ngày chưa nấu mâm nào không tính calo.
            </T>
          </Card>
        </>
      ) : null}
    </Screen>
  );
}
