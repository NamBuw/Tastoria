import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Platform, Pressable, type TextStyle, View } from 'react-native';

import { api, call, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { Icon } from '@/components/domain';
import { Button, Chip, Empty, ErrorBox, Field, Loading, Notice, Row, Screen, Section, Segmented, Sheet, T, UnderlineTabs } from '@/components/ui';
import { goTab } from '@/lib/nav';
import { qk } from '@/lib/queries';
import { radius, space, TOUCH, useLayout, useTheme } from '@/theme';

type DataRequest = Schemas['AdminDataRequest'];
type DsrStatus = Schemas['DataRequestStatus'];
type DsrType = Schemas['DataRequestType'];
type ModelName = Schemas['ModelName'];

const WRAP_STYLE: TextStyle | undefined =
  Platform.OS === 'web' ? ({ overflowWrap: 'anywhere', wordBreak: 'break-word' } as unknown as TextStyle) : undefined;

const DSR_STATUS_LABEL: Record<DsrStatus, string> = {
  received: 'Mới nhận',
  in_progress: 'Đang xử lý',
  completed: 'Hoàn tất',
  rejected: 'Từ chối',
};

const DSR_TYPE_LABEL: Record<DsrType, string> = {
  access: 'Truy cập',
  export: 'Xuất dữ liệu',
  delete: 'Xoá tài khoản',
  correct: 'Sửa dữ liệu',
  restrict: 'Hạn chế xử lý',
  object: 'Phản đối xử lý',
  withdraw: 'Rút đồng ý',
};

const MODEL_STATUS_VI: Record<Schemas['ModelVersion']['status'], string> = {
  candidate: 'Ứng viên',
  validated: 'Đã kiểm định',
  rejected: 'Bị từ chối',
  retired: 'Ngừng dùng',
};

const MODEL_NAMES: ModelName[] = [
  'detector',
  'freshness',
  'ranker',
  'substitution',
  'meal_calorie',
  'dish_classifier',
  'mushroom_classifier',
];

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function formatMetricValue(val: unknown): string {
  if (typeof val === 'number') {
    return Number.isFinite(val) ? String(Math.round(val * 1000) / 1000) : 'không xác định';
  }
  if (typeof val === 'string' || typeof val === 'boolean') {
    return String(val);
  }
  if (Array.isArray(val)) {
    return val.slice(0, 4).map(formatMetricValue).join(', ');
  }
  if (val && typeof val === 'object') {
    const entries = Object.entries(val as Record<string, unknown>);
    if (!entries.length) return 'trống';
    return entries
      .slice(0, 4)
      .map(([sk, sv]) => `${sk}: ${formatMetricValue(sv)}`)
      .join(', ');
  }
  return 'trống';
}

function fmtIsoShort(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function isSlaUrgent(dueAt: string, status: DsrStatus): 'overdue' | 'soon' | null {
  if (status === 'completed' || status === 'rejected') return null;
  const diff = new Date(dueAt).getTime() - Date.now();
  if (diff <= 0) return 'overdue';
  if (diff <= 48 * 3600_000) return 'soon';
  return null;
}

/** Bảng Quản trị (/quan-tri): strictly role-gated (`admin` | `ml_operator`), zero unauthorized `/admin/*` requests. */
export default function AdminConsole() {
  const { status, user } = useSession();

  if (status === 'loading') {
    return (
      <Screen variant="focused">
        <Loading />
      </Screen>
    );
  }

  if (status !== 'signedIn' || (user?.role !== 'admin' && user?.role !== 'ml_operator')) {
    return (
      <Screen testID="screen-admin-forbidden" variant="focused">
        <T v="h1" accessibilityRole="header">
          Quản trị hệ thống
        </T>
        <Notice tone="warn">
          <T v="h2" accessibilityRole="header">
            Không có quyền truy cập
          </T>
          <T>Trang này chỉ dành cho quản trị viên hoặc người vận hành mô hình.</T>
        </Notice>
        <Button label="Về Bếp nhà" onPress={() => goTab('/bep')} />
      </Screen>
    );
  }

  return user.role === 'admin' ? <AdminWorkspace /> : <MlOperatorWorkspace />;
}

// ---- admin role: DSR Queue + Audit Log ----------------------------------------------------------

function AdminWorkspace() {
  const { c } = useTheme();
  const [tab, setTab] = useState<'data-requests' | 'audit-log'>('data-requests');

  return (
    <Screen testID="screen-admin">
      <Row style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <View style={{ gap: 2 }}>
          <T v="h1" accessibilityRole="header">
            Quản trị hệ thống
          </T>
          <T v="small" tone="muted">
            Vai trò: Quản trị viên
          </T>
        </View>
        <View style={{ backgroundColor: c.accentSoft, borderRadius: radius.sm, paddingHorizontal: space.md, paddingVertical: 4 }}>
          <Row gap={space.xs} style={{ flexWrap: 'nowrap' }}>
            <Icon name="shield" size={16} color={c.accent} />
            <T v="small" tone="accent" style={{ fontWeight: '600' }}>
              Quản trị
            </T>
          </Row>
        </View>
      </Row>

      <UnderlineTabs
        options={[
          ['data-requests', 'Yêu cầu DSR', 'admin-tab-data-requests'],
          ['audit-log', 'Nhật ký kiểm toán', 'admin-tab-audit-log'],
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === 'data-requests' ? <AdminDsrTab /> : <AdminAuditTab />}
    </Screen>
  );
}

function AdminDsrTab() {
  const { c } = useTheme();
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<DsrStatus | 'all'>('all');
  const [typeFilter, setTypeFilter] = useState<DsrType | 'all'>('all');
  const [resolving, setResolving] = useState<DataRequest | null>(null);
  const [resolveStatus, setResolveStatus] = useState<Schemas['DataRequestResolve']['status']>('completed');
  const [note, setNote] = useState('');

  const q = useInfiniteQuery({
    queryKey: qk.adminDataRequests({ status: statusFilter, type: typeFilter }),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/admin/data-requests', {
          params: {
            query: {
              status: statusFilter === 'all' ? undefined : [statusFilter],
              type: typeFilter === 'all' ? undefined : [typeFilter],
              cursor: pageParam,
              limit: 25,
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const resolve = useMutation({
    mutationFn: () =>
      call(
        api.POST('/admin/data-requests/{id}/resolve', {
          params: { path: { id: resolving!.id } },
          body: { status: resolveStatus, note: note.trim() },
        }),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'data-requests'] });
      qc.invalidateQueries({ queryKey: ['admin', 'audit-log'] });
      setResolving(null);
      setNote('');
    },
  });

  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <View style={{ gap: space.md }}>
      <Row gap={space.sm}>
        {(['all', 'received', 'in_progress', 'completed', 'rejected'] as const).map((s) => (
          <Chip
            key={s}
            label={s === 'all' ? 'Mọi trạng thái' : DSR_STATUS_LABEL[s]}
            selected={statusFilter === s}
            onPress={() => setStatusFilter(s)}
          />
        ))}
      </Row>
      <Row gap={space.sm}>
        {(['all', 'correct', 'restrict', 'object', 'export', 'delete'] as const).map((t) => (
          <Chip
            key={t}
            label={t === 'all' ? 'Mọi loại' : DSR_TYPE_LABEL[t]}
            selected={typeFilter === t}
            onPress={() => setTypeFilter(t)}
          />
        ))}
      </Row>

      {q.isLoading ? <Loading rows={3} /> : null}
      {q.error ? <ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} /> : null}
      {q.data && rows.length === 0 ? <Empty title="Không có yêu cầu dữ liệu nào." /> : null}

      <View style={{ gap: space.sm }}>
        {rows.map((row) => {
          const manual = row.type === 'correct' || row.type === 'restrict' || row.type === 'object';
          const canResolve = manual && row.status !== 'completed' && row.status !== 'rejected';
          const sla = isSlaUrgent(row.due_at, row.status);
          return (
            <View key={row.id} style={{ backgroundColor: c.surface, borderColor: c.hairline, borderWidth: 1, borderRadius: radius.lg, padding: space.lg, gap: space.sm }}>
              <Row style={{ justifyContent: 'space-between', flexWrap: 'wrap' }} gap={space.sm}>
                <Row gap={space.sm}>
                  <View style={{ backgroundColor: c.surfaceAlt, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 2 }}>
                    <T v="small" style={{ fontWeight: '600' }}>
                      {DSR_TYPE_LABEL[row.type]}
                    </T>
                  </View>
                  <View
                    style={{
                      backgroundColor: row.status === 'completed' ? c.herbSoft : row.status === 'rejected' ? c.dangerSoft : c.infoSoft,
                      borderRadius: radius.sm,
                      paddingHorizontal: space.sm,
                      paddingVertical: 2,
                    }}>
                    <T
                      v="small"
                      tone={row.status === 'completed' ? 'herb' : row.status === 'rejected' ? 'danger' : 'info'}
                      style={{ fontWeight: '600' }}>
                      {DSR_STATUS_LABEL[row.status]}
                    </T>
                  </View>
                  {sla ? (
                    <View
                      style={{
                        backgroundColor: sla === 'overdue' ? c.dangerSoft : c.warnSoft,
                        borderRadius: radius.sm,
                        paddingHorizontal: space.sm,
                        paddingVertical: 2,
                      }}>
                      <T v="small" tone={sla === 'overdue' ? 'danger' : 'warn'} style={{ fontWeight: '600' }}>
                        {sla === 'overdue' ? 'Quá hạn SLA' : 'Sắp đến hạn'}
                      </T>
                    </View>
                  ) : null}
                </Row>
                <T v="small" tone="muted" tabular>
                  Hạn: {fmtIsoShort(row.due_at)}
                </T>
              </Row>

              <T v="small" tone="muted" tabular style={WRAP_STYLE}>
                Mã chủ thể: {row.subject_ref.slice(0, 16)}…, nhận: {fmtIsoShort(row.received_at)}
              </T>
              {row.note ? <T>{row.note}</T> : null}

              <Row style={{ justifyContent: 'flex-end' }}>
                {canResolve ? (
                  <Button
                    label="Xử lý"
                    kind="secondary"
                    testID={`dsr-resolve-${row.id}`}
                    onPress={() => {
                      setResolving(row);
                      setResolveStatus('completed');
                      setNote('');
                    }}
                  />
                ) : !manual ? (
                  <T v="small" tone="muted">
                    Tự động
                  </T>
                ) : null}
              </Row>
            </View>
          );
        })}
      </View>

      {q.hasNextPage ? (
        <Button label="Tải thêm" kind="secondary" onPress={() => q.fetchNextPage()} loading={q.isFetchingNextPage} />
      ) : null}

      <Sheet visible={!!resolving} onClose={() => setResolving(null)} title="Xử lý yêu cầu dữ liệu">
        {resolving ? (
          <>
            <T v="small" tone="muted" tabular style={WRAP_STYLE}>
              Loại: {DSR_TYPE_LABEL[resolving.type]}, mã chủ thể: {resolving.subject_ref.slice(0, 16)}…
            </T>
            <Segmented
              label="Trạng thái xử lý"
              options={[
                ['in_progress', 'Đang xử lý'],
                ['completed', 'Hoàn tất'],
                ['rejected', 'Từ chối'],
              ]}
              value={resolveStatus}
              onChange={setResolveStatus}
            />
            <Field
              label="Ghi chú xử lý (bắt buộc)"
              testID="dsr-resolve-note"
              value={note}
              onChangeText={setNote}
              multiline
              maxLength={2000}
              placeholder="Ghi rõ việc đã xử lý hoặc lý do từ chối…"
            />
            {resolve.error ? <ErrorBox message={errorText(resolve.error)} /> : null}
            <Button
              label="Xác nhận xử lý"
              testID="dsr-resolve-submit"
              disabled={!note.trim()}
              loading={resolve.isPending}
              onPress={() => resolve.mutate()}
            />
          </>
        ) : null}
      </Sheet>
    </View>
  );
}

function AdminAuditTab() {
  const { c } = useTheme();
  const [entity, setEntity] = useState('');
  const [action, setAction] = useState('');
  const [actorId, setActorId] = useState('');
  const [debounced, setDebounced] = useState({ entity: '', action: '', actorId: '' });

  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced({
        entity: entity.trim(),
        action: action.trim(),
        actorId: actorId.trim(),
      });
    }, 350);
    return () => clearTimeout(t);
  }, [entity, action, actorId]);

  const actorValid = !debounced.actorId || UUID_RE.test(debounced.actorId);
  const actorInputTrimmed = actorId.trim();
  const showActorFormatErr = Boolean(actorInputTrimmed && !UUID_RE.test(actorInputTrimmed));

  const q = useInfiniteQuery({
    queryKey: qk.adminAuditLog({
      entity: debounced.entity,
      action: debounced.action,
      actor_user_id: actorValid ? debounced.actorId : '',
    }),
    enabled: actorValid,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/admin/audit-log', {
          params: {
            query: {
              entity: debounced.entity || undefined,
              action: debounced.action || undefined,
              actor_user_id: debounced.actorId || undefined,
              cursor: pageParam,
              limit: 30,
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <View style={{ gap: space.md }}>
      <Row gap={space.md}>
        <View style={{ flex: 1, minWidth: 160 }}>
          <Field label="Thực thể (entity)" value={entity} onChangeText={setEntity} placeholder="dsr_requests…" autoCapitalize="none" />
        </View>
        <View style={{ flex: 1, minWidth: 160 }}>
          <Field label="Hành động (action)" value={action} onChangeText={setAction} placeholder="dsr_resolve…" autoCapitalize="none" />
        </View>
        <View style={{ flex: 1, minWidth: 180 }}>
          <Field
            label="Mã người thực hiện"
            testID="audit-actor-filter"
            value={actorId}
            onChangeText={setActorId}
            placeholder="Nhập mã định danh hợp lệ…"
            autoCapitalize="none"
            error={showActorFormatErr ? 'Mã định danh không hợp lệ (cần dạng chuẩn 36 ký tự).' : undefined}
          />
        </View>
      </Row>

      {q.isLoading && actorValid ? <Loading rows={4} /> : null}
      {q.error ? <ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} /> : null}
      {q.data && rows.length === 0 ? <Empty title="Chưa có bản ghi kiểm toán." /> : null}

      <View style={{ gap: space.sm }}>
        {rows.map((entry) => (
          <View key={entry.id} style={{ backgroundColor: c.surface, borderColor: c.hairline, borderWidth: 1, borderRadius: radius.lg, padding: space.lg, gap: space.xs }}>
            <Row style={{ justifyContent: 'space-between', flexWrap: 'wrap' }} gap={space.xs}>
              <T v="label">
                {entry.action} ({entry.entity})
              </T>
              <T v="small" tone="muted" tabular>
                {fmtIsoShort(entry.created_at)}
              </T>
            </Row>
            <T v="small" tone="muted" tabular style={WRAP_STYLE}>
              Vai trò: {entry.actor_role}
              {entry.entity_id ? `, ID: ${entry.entity_id}` : ''}
            </T>
            {entry.request_id ? (
              <T v="small" tone="muted" tabular style={[{ backgroundColor: c.surfaceAlt, padding: 6, borderRadius: radius.sm }, WRAP_STYLE]}>
                request_id: {entry.request_id}
              </T>
            ) : null}
          </View>
        ))}
      </View>

      {q.hasNextPage ? (
        <Button label="Tải thêm" kind="secondary" onPress={() => q.fetchNextPage()} loading={q.isFetchingNextPage} />
      ) : null}
    </View>
  );
}

// ---- ml_operator role: Models + Surveys ---------------------------------------------------------

function MlOperatorWorkspace() {
  const { c } = useTheme();
  const [tab, setTab] = useState<'models' | 'surveys'>('models');

  return (
    <Screen testID="screen-admin">
      <Row style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <View style={{ gap: 2 }}>
          <T v="h1" accessibilityRole="header">
            Quản trị hệ thống
          </T>
          <T v="small" tone="muted">
            Vai trò: Vận hành mô hình
          </T>
        </View>
        <View style={{ backgroundColor: c.infoSoft, borderRadius: radius.sm, paddingHorizontal: space.md, paddingVertical: 4 }}>
          <Row gap={space.xs} style={{ flexWrap: 'nowrap' }}>
            <Icon name="shield" size={16} color={c.info} />
            <T v="small" tone="info" style={{ fontWeight: '600' }}>
              Vận hành
            </T>
          </Row>
        </View>
      </Row>

      <UnderlineTabs
        options={[
          ['models', 'Đăng ký mô hình', 'admin-tab-models'],
          ['surveys', 'Đợt khảo sát', 'admin-tab-surveys'],
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === 'models' ? <MlModelsTab /> : <MlSurveysTab />}
    </Screen>
  );
}

function MlModelsTab() {
  const { c } = useTheme();
  const { isTabletUp: wide } = useLayout();
  const qc = useQueryClient();
  const [nameFilter, setNameFilter] = useState<ModelName | 'all'>('all');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const q = useInfiniteQuery({
    queryKey: qk.adminModels({ name: nameFilter }),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/admin/models', {
          params: {
            query: {
              name: nameFilter === 'all' ? undefined : nameFilter,
              cursor: pageParam,
              limit: 30,
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const pages = q.data?.pages ?? [];
  const deployments = pages[0]?.deployments ?? [];
  const items = pages.flatMap((p) => p.items);
  const allCached = qc.getQueryData<{ pages?: { items: Schemas['ModelVersion'][] }[] }>(qk.adminModels({ name: 'all' }));

  const byId = new Map<string, Schemas['ModelVersion']>();
  for (const p of allCached?.pages ?? []) {
    for (const m of p.items) byId.set(m.id, m);
  }
  items.forEach((m) => byId.set(m.id, m));

  const copyCli = async (id: string, cmd: string) => {
    if (Platform.OS === 'web' && typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(cmd).catch(() => {});
    }
    setCopiedId(id);
  };

  return (
    <View style={{ gap: space.lg }}>
      <Section title="Bản mô hình đang triển khai">
        <View style={{ flexDirection: wide ? 'row' : 'column', flexWrap: wide ? 'wrap' : 'nowrap', gap: space.md }}>
          {MODEL_NAMES.map((mn) => {
            const dep = deployments.find((d) => d.name === mn);
            const activeVer = dep ? byId.get(dep.active_version_id) : undefined;
            return (
              <View
                key={mn}
                testID={`model-deploy-card-${mn}`}
                style={[{ backgroundColor: c.surface, borderColor: c.hairline, borderWidth: 1, borderRadius: radius.lg, padding: space.lg, gap: space.sm }, wide ? { flex: 1, minWidth: 220 } : undefined]}>
                <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                  <T v="title">{mn}</T>
                  <View
                    style={{
                      backgroundColor: dep ? c.herbSoft : c.surfaceAlt,
                      borderRadius: radius.sm,
                      paddingHorizontal: space.sm,
                      paddingVertical: 2,
                    }}>
                    <T v="small" tone={dep ? 'herb' : 'muted'} style={{ fontWeight: '600' }}>
                      {dep ? 'Đang chạy' : 'Chưa gán'}
                    </T>
                  </View>
                </Row>
                <T v="label" tabular style={WRAP_STYLE}>
                  {activeVer ? `v${activeVer.version}` : dep ? dep.active_version_id.slice(0, 12) : 'Chưa có'}
                </T>
                {dep ? (
                  <T v="small" tone="muted" tabular>
                    Chuyển lúc: {fmtIsoShort(dep.switched_at)}
                  </T>
                ) : null}
              </View>
            );
          })}
        </View>
      </Section>

      <Row gap={space.sm}>
        <Chip label="Tất cả mô hình" selected={nameFilter === 'all'} onPress={() => setNameFilter('all')} />
        {MODEL_NAMES.map((mn) => (
          <Chip key={mn} label={mn} selected={nameFilter === mn} onPress={() => setNameFilter(mn)} />
        ))}
      </Row>

      {q.isLoading ? <Loading rows={3} /> : null}
      {q.error ? <ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} /> : null}
      {q.data && items.length === 0 ? <Empty title="Chưa đăng ký mô hình nào." /> : null}

      <View style={{ gap: space.md }}>
        {items.map((m) => {
          const cliSnippet = `tastoria mlops gate ${m.name} ${m.version} && tastoria mlops deploy ${m.name} ${m.version}`;
          const metricEntries = Object.entries(m.metrics ?? {}).slice(0, 4);
          return (
            <View key={m.id} style={{ backgroundColor: c.surface, borderColor: c.hairline, borderWidth: 1, borderRadius: radius.lg, padding: space.lg, gap: space.sm }}>
              <Row style={{ justifyContent: 'space-between', flexWrap: 'wrap' }} gap={space.sm}>
                <Row gap={space.sm}>
                  <T v="title">
                    {m.name} ({m.version})
                  </T>
                  {m.is_active ? (
                    <View style={{ backgroundColor: c.herbSoft, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 2 }}>
                      <T v="small" tone="herb" style={{ fontWeight: '600' }}>
                        Đang chạy
                      </T>
                    </View>
                  ) : null}
                </Row>
                <View style={{ backgroundColor: c.surfaceAlt, borderRadius: radius.sm, paddingHorizontal: space.sm, paddingVertical: 2 }}>
                  <T v="small">{MODEL_STATUS_VI[m.status] ?? m.status}</T>
                </View>
              </Row>

              <T v="small" tone="muted" tabular style={WRAP_STYLE}>
                SHA-256: {m.sha256.slice(0, 12)}
                {m.preprocess_version ? `, preprocess: ${m.preprocess_version}` : ''}
              </T>

              {metricEntries.length ? (
                <Row gap={space.md}>
                  {metricEntries.map(([k, val]) => (
                    <T key={k} v="small" tabular style={WRAP_STYLE}>
                      {k}: {formatMetricValue(val)}
                    </T>
                  ))}
                </Row>
              ) : null}

              <View style={{ backgroundColor: c.surfaceAlt, borderRadius: radius.md, padding: space.sm, gap: space.xs }}>
                <T v="small" tabular style={WRAP_STYLE}>
                  {cliSnippet}
                </T>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Sao chép lệnh CLI cho ${m.name} ${m.version}`}
                  onPress={() => void copyCli(m.id, cliSnippet)}
                  style={{ minHeight: TOUCH, justifyContent: 'center', alignSelf: 'flex-start', paddingHorizontal: space.sm }}>
                  <T v="label" tone="accent">
                    {copiedId === m.id ? 'Đã sao chép lệnh CLI' : 'Sao chép lệnh CLI'}
                  </T>
                </Pressable>
              </View>
            </View>
          );
        })}
      </View>

      {q.hasNextPage ? (
        <Button label="Tải thêm" kind="secondary" onPress={() => q.fetchNextPage()} loading={q.isFetchingNextPage} />
      ) : null}
    </View>
  );
}

function MlSurveysTab() {
  const { c } = useTheme();
  const q = useInfiniteQuery({
    queryKey: qk.adminSurveys,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      call(api.GET('/admin/surveys', { params: { query: { cursor: pageParam, limit: 30 } } })),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <View style={{ gap: space.md }}>
      {q.isLoading ? <Loading rows={3} /> : null}
      {q.error ? <ErrorBox message={errorText(q.error)} onRetry={() => q.refetch()} /> : null}
      {q.data && rows.length === 0 ? <Empty title="Chưa có đợt khảo sát." /> : null}

      <View style={{ gap: space.md }}>
        {rows.map((s) => {
          const pct = s.respondents_total > 0 ? Math.round((s.respondents_completed / s.respondents_total) * 100) : 0;
          return (
            <View key={s.id} style={{ backgroundColor: c.surface, borderColor: c.hairline, borderWidth: 1, borderRadius: radius.lg, padding: space.lg, gap: space.sm }}>
              <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                <T v="title">Phiên bản {s.version}</T>
                <View
                  style={{
                    backgroundColor: s.is_open ? c.herbSoft : c.surfaceAlt,
                    borderRadius: radius.sm,
                    paddingHorizontal: space.sm,
                    paddingVertical: 2,
                  }}>
                  <T v="small" tone={s.is_open ? 'herb' : 'muted'} style={{ fontWeight: '600' }}>
                    {s.is_open ? 'Đang mở' : 'Đã đóng'}
                  </T>
                </View>
              </Row>
              <T v="small" tone="muted" tabular>
                Món neo: {s.n_anchor}, ngẫu nhiên: {s.n_random}, tạo lúc: {fmtIsoShort(s.created_at)}
              </T>
              <View style={{ gap: 4 }}>
                <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                  <T v="small">Tiến độ hoàn thành</T>
                  <T v="label" tabular>
                    {s.respondents_completed} / {s.respondents_total} ({pct}%)
                  </T>
                </Row>
                <View style={{ height: 8, borderRadius: radius.sm, backgroundColor: c.surfaceAlt, overflow: 'hidden' }}>
                  <View style={{ width: `${Math.min(100, pct)}%`, height: 8, borderRadius: radius.sm, backgroundColor: c.accent }} />
                </View>
              </View>
            </View>
          );
        })}
      </View>

      {q.hasNextPage ? (
        <Button label="Tải thêm" kind="secondary" onPress={() => q.fetchNextPage()} loading={q.isFetchingNextPage} />
      ) : null}
    </View>
  );
}
