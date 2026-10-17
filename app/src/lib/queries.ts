import { useQuery } from '@tanstack/react-query';

import { api, call } from '@/api/client';
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
};

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

/** Lots in stock (incl. not_seen), most urgent first. */
export function useLots() {
  const { status } = useSession();
  return useQuery({
    queryKey: qk.lots('open'),
    queryFn: () =>
      call(api.GET('/pantry/lots', { params: { query: { status: ['in_stock', 'not_seen'], sort: 'urgency', limit: 100 } } })),
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
