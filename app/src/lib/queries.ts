import { useQuery } from '@tanstack/react-query';

import { api, call, type Schemas } from '@/api/client';
import { useSession } from '@/auth/session';

/** Query keys in one place so mutations invalidate the right lists. */
export const qk = {
  reference: ['reference'] as const,
  profile: ['profile'] as const,
  settings: ['settings'] as const,
  consents: ['consents'] as const,
  lots: (status: string) => ['lots', status] as const,
  latestPlan: (meal: string) => ['plan', 'latest', meal] as const,
  plan: (id: string) => ['plan', id] as const,
  shopping: ['shopping'] as const,
  journal: (week: string) => ['journal', week] as const,
  session: (id: string) => ['cook', id] as const,
  recipe: (id: string) => ['recipe', id] as const,
  recipes: (params: Record<string, unknown>) => ['recipes', params] as const,
  adminDataRequests: (filters: Record<string, unknown> = {}) => ['admin', 'data-requests', filters] as const,
  adminAuditLog: (filters: Record<string, unknown> = {}) => ['admin', 'audit-log', filters] as const,
  adminModels: (filters: Record<string, unknown> = {}) => ['admin', 'models', filters] as const,
  adminSurveys: ['admin', 'surveys'] as const,
  authSessions: ['auth', 'sessions'] as const,
};

/** Follows keyset `next_cursor` pagination cleanly past 100 items. */
export async function fetchAllPages<T>(
  fetchPage: (cursor?: string) => Promise<{ items: T[]; next_cursor?: string | null }>,
  maxPages = 20,
): Promise<{ items: T[]; next_cursor: string | null }> {
  const all: T[] = [];
  let cursor: string | undefined;
  let page = 0;
  do {
    const res = await fetchPage(cursor);
    all.push(...(res.items ?? []));
    cursor = res.next_cursor ?? undefined;
    page += 1;
  } while (cursor && page < maxPages);
  return { items: all, next_cursor: cursor ?? null };
}

export function useReference() {
  return useQuery({
    queryKey: qk.reference,
    queryFn: () => call(api.GET('/reference')),
    staleTime: 60 * 60_000,
  });
}

export function useProfile() {
  const { status } = useSession();
  return useQuery({
    queryKey: qk.profile,
    queryFn: () => call(api.GET('/me/profile')),
    enabled: status === 'signedIn',
  });
}

export function useSettings() {
  const { status } = useSession();
  return useQuery({
    queryKey: qk.settings,
    queryFn: () => call(api.GET('/me/settings')),
    enabled: status === 'signedIn',
  });
}

export function useConsents() {
  const { status } = useSession();
  return useQuery({
    queryKey: qk.consents,
    queryFn: () => call(api.GET('/me/consents')),
    enabled: status === 'signedIn',
  });
}

export function useHasConsent(purpose: 'health_profile' | 'personalization' | 'photo_contribution') {
  const q = useConsents();
  return q.data?.items.some((i) => i.purpose_code === purpose && i.state === 'granted') ?? false;
}

/** Lots in stock (incl. not_seen), sorted by urgency (default) or created_at, following all keyset pages. */
export function useLots(sort: 'urgency' | 'created_at' = 'urgency') {
  const { status } = useSession();
  return useQuery({
    queryKey: sort === 'urgency' ? qk.lots('open') : qk.lots(`open-${sort}`),
    queryFn: () =>
      fetchAllPages((cursor) =>
        call(api.GET('/pantry/lots', { params: { query: { status: ['in_stock', 'not_seen'], sort, cursor, limit: 100 } } })),
      ),
    enabled: status === 'signedIn',
  });
}

/** Meal of "now": lunch until 15:00, then dinner (plan lifecycle in backend README). */
export function currentMeal(d = new Date()): 'lunch' | 'dinner' {
  return d.getHours() < 15 ? 'lunch' : 'dinner';
}

export const MEAL_LABEL = { lunch: 'Bữa trưa', dinner: 'Bữa tối' } as const;

/** Latest proposed/accepted plan of the meal today; null on 404. */
export function useLatestPlan(meal: 'lunch' | 'dinner') {
  const { status } = useSession();
  return useQuery({
    queryKey: qk.latestPlan(meal),
    queryFn: async () => {
      const r = await api.GET('/meal-plans/latest', { params: { query: { meal } } });
      if (r.response.status === 404) return null;
      return call(Promise.resolve(r));
    },
    enabled: status === 'signedIn',
  });
}

export type RecipeListParams = {
  q?: string;
  slot?: 'man' | 'rau' | 'canh';
  tag?: string;
  method_code?: string;
  max_minutes?: number;
  max_kcal?: number;
  pantry_match?: boolean;
  cursor?: string;
  limit?: number;
};

export function useRecipes(params: RecipeListParams = {}) {
  const { status } = useSession();
  return useQuery({
    queryKey: qk.recipes(params),
    queryFn: () => call(api.GET('/recipes', { params: { query: params } })),
    enabled: status === 'signedIn',
  });
}

export type AdminDataRequestFilters = {
  status?: Schemas['DataRequestStatus'][];
  type?: Schemas['DataRequestType'][];
  cursor?: string;
  limit?: number;
};

export function useAdminDataRequests(filters: AdminDataRequestFilters = {}) {
  const { status, user } = useSession();
  return useQuery({
    queryKey: qk.adminDataRequests(filters),
    queryFn: () => call(api.GET('/admin/data-requests', { params: { query: filters } })),
    enabled: status === 'signedIn' && user?.role === 'admin',
  });
}

export type AdminAuditLogFilters = {
  actor_user_id?: string;
  entity?: string;
  action?: string;
  from?: string;
  to?: string;
  cursor?: string;
  limit?: number;
};

export function useAdminAuditLog(filters: AdminAuditLogFilters = {}) {
  const { status, user } = useSession();
  return useQuery({
    queryKey: qk.adminAuditLog(filters),
    queryFn: () => call(api.GET('/admin/audit-log', { params: { query: filters } })),
    enabled: status === 'signedIn' && user?.role === 'admin',
  });
}

export type AdminModelFilters = {
  name?: Schemas['ModelName'];
  status?: 'candidate' | 'validated' | 'rejected' | 'retired';
  cursor?: string;
  limit?: number;
};

export function useAdminModels(filters: AdminModelFilters = {}) {
  const { status, user } = useSession();
  return useQuery({
    queryKey: qk.adminModels(filters),
    queryFn: () => call(api.GET('/admin/models', { params: { query: filters } })),
    enabled: status === 'signedIn' && user?.role === 'ml_operator',
  });
}

export function useAdminSurveys(cursor?: string) {
  const { status, user } = useSession();
  return useQuery({
    queryKey: cursor ? [...qk.adminSurveys, cursor] : qk.adminSurveys,
    queryFn: () => call(api.GET('/admin/surveys', { params: { query: { cursor, limit: 50 } } })),
    enabled: status === 'signedIn' && user?.role === 'ml_operator',
  });
}
