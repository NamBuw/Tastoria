import AsyncStorage from '@react-native-async-storage/async-storage';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, screen, waitFor } from '@testing-library/react-native';
import React from 'react';

import { api, rawRequest, setSession } from '@/api/client';
import Finished from '@/app/nau-xong/[id]';
import { useCookSession } from '@/lib/cooking';
import { useIdempotencyKey } from '@/lib/idempotency';
import {
  clearCompleteOutcome,
  enqueueComplete,
  enqueueEvents,
  flush,
  getCompleteOutcome,
  isOutboxPausedForAuth,
} from '@/lib/outbox';
import { getScopedKey, purgeUserCaches } from '@/lib/storage';

import { mockNavState, mockSessionState } from '../../jest.setup';
import { errRes, okRes, renderWithProviders } from './test-utils';

jest.mock('@/api/client', () => {
  const actual = jest.requireActual('@/api/client');
  return {
    ...actual,
    rawRequest: jest.fn(),
  };
});

const mockedRawRequest = rawRequest as jest.MockedFunction<typeof rawRequest>;

const sessionFor = (userId: string) => ({
  access_token: `tok-${userId}`,
  refresh_token: null,
  token_type: 'Bearer' as const,
  expires_in: 900 as const,
  refresh_expires_at: '2026-12-01T00:00:00Z',
  user: {
    id: userId,
    email: `${userId}@example.vn`,
    role: 'user' as const,
    status: 'active' as const,
    created_at: '2026-11-01T00:00:00Z',
  },
});

async function renderWithHookCook(id: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const hook = await renderHook(() => useCookSession(id), { wrapper });
  return { ...hook, qc };
}

describe('outbox & idempotency', () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
    mockedRawRequest.mockReset();
    mockSessionState.status = 'signedIn';
    mockSessionState.user = { id: 'user-1', email: 'user-1@example.vn', role: 'user', onboarding_completed: true };
    await setSession(sessionFor('user-1'));
  });

  afterEach(async () => {
    jest.restoreAllMocks();
    await setSession(null);
  });

  it('pauses queue on 401 without dropping entry, then resumes after re-authentication', async () => {
    mockedRawRequest.mockResolvedValueOnce({
      status: 401,
      json: { code: 'unauthenticated', detail: 'Token expired' },
    });

    await enqueueComplete('sess-401', { completed_at: '2026-11-18T12:00:00Z', feedback: [] }, 'user-1');

    expect(isOutboxPausedForAuth('user-1')).toBe(true);
    expect(await getCompleteOutcome('sess-401', 'user-1')).toEqual({
      state: 'pending',
      authRequired: true,
    });

    // While paused for auth, manual flush does NOT drop or hammer API
    mockedRawRequest.mockClear();
    await flush('user-1');
    expect(mockedRawRequest).not.toHaveBeenCalled();

    // Re-authenticating clears the pause and completes cleanly
    mockedRawRequest.mockResolvedValueOnce({
      status: 200,
      json: {
        cook_session: { id: 'sess-401', status: 'completed', undo_deadline: '2026-11-18T12:10:00Z' },
        deductions: [],
        shortfalls: [],
      },
    });
    await setSession(sessionFor('user-1'));
    await waitFor(async () => {
      const done = await getCompleteOutcome('sess-401', 'user-1');
      expect(done?.state).toBe('done');
    });
    expect(isOutboxPausedForAuth('user-1')).toBe(false);
  });

  it('isolates outbox queues per userId, refuses cross-account flush, and purges user caches cleanly', async () => {
    await AsyncStorage.setItem(
      getScopedKey('user-a', 'outbox.v1'),
      JSON.stringify([
        {
          id: 'ev-a',
          userId: 'user-a',
          kind: 'events',
          method: 'POST',
          path: '/events',
          body: { events: [] },
          createdAt: '2026-11-24T10:00:00Z',
          attempts: 0,
        },
      ]),
    );
    await AsyncStorage.setItem(getScopedKey('user-b', 'cook.s1'), JSON.stringify({ id: 's1' }));

    await setSession(sessionFor('user-b'));
    await flush('user-a');
    expect(mockedRawRequest).not.toHaveBeenCalled();

    await purgeUserCaches('user-a');
    expect(await AsyncStorage.getItem(getScopedKey('user-a', 'outbox.v1'))).toBeNull();
    expect(await AsyncStorage.getItem(getScopedKey('user-b', 'cook.s1'))).not.toBeNull();
  });

  it('merge-removes only processed IDs in flush() so concurrent enqueueEvents is preserved', async () => {
    await AsyncStorage.setItem(
      getScopedKey('user-1', 'outbox.v1'),
      JSON.stringify([
        {
          id: 'ev-old',
          userId: 'user-1',
          kind: 'events',
          method: 'POST',
          path: '/events',
          body: { events: [] },
          createdAt: '2026-11-24T10:00:00Z',
          attempts: 0,
        },
      ]),
    );

    let releaseFirst!: () => void;
    mockedRawRequest.mockImplementationOnce(
      () =>
        new Promise((res) => {
          releaseFirst = () => res({ status: 200, json: {} });
        }),
    );

    const flushPromise = flush('user-1');
    await waitFor(() => expect(mockedRawRequest).toHaveBeenCalledTimes(1));

    await enqueueEvents([{ type: 'viewed', recipe_id: 'r1' }], 'user-1');
    releaseFirst();
    await flushPromise;

    const rawAfter = await AsyncStorage.getItem(getScopedKey('user-1', 'outbox.v1'));
    const remaining = JSON.parse(rawAfter ?? '[]') as { id: string }[];
    expect(remaining).toHaveLength(1);
    expect(remaining[0].id).not.toBe('ev-old');
  });

  it('keeps entries queued on status 0, 500, and 429 with identical Idempotency-Key until 200', async () => {
    mockedRawRequest
      .mockRejectedValueOnce(new Error('offline')) // status 0
      .mockResolvedValueOnce({ status: 500, json: { code: 'internal_error' } })
      .mockResolvedValueOnce({ status: 429, json: { code: 'rate_limited' } })
      .mockResolvedValueOnce({
        status: 200,
        json: {
          cook_session: { id: 'sess-retry', status: 'completed', undo_deadline: '2026-11-18T12:10:00Z' },
          deductions: [],
          shortfalls: [],
        },
      });

    await enqueueComplete('sess-retry', { completed_at: '2026-11-18T12:00:00Z', feedback: [] }, 'user-1');
    expect(await getCompleteOutcome('sess-retry', 'user-1')).toEqual({ state: 'pending' });

    await flush('user-1'); // 500
    expect(await getCompleteOutcome('sess-retry', 'user-1')).toEqual({ state: 'pending' });

    await flush('user-1'); // 429
    expect(await getCompleteOutcome('sess-retry', 'user-1')).toEqual({ state: 'pending' });

    await flush('user-1'); // 200
    const done = await getCompleteOutcome('sess-retry', 'user-1');
    expect(done?.state).toBe('done');

    expect(mockedRawRequest).toHaveBeenCalledTimes(4);
    const keys = mockedRawRequest.mock.calls.map((c) => c[3]?.['Idempotency-Key']);
    expect(keys[0]).toBeTruthy();
    expect(new Set(keys).size).toBe(1);
  });

  it('cooking cache is user-scoped and falls back ONLY on network error (status 0), never on 401/404', async () => {
    const cachedSession = {
      id: 'cs-1',
      meal_plan_id: 'mp-1',
      status: 'in_progress',
      started_at: '2026-11-24T10:00:00Z',
      schedule: [],
    };
    await AsyncStorage.setItem(getScopedKey('user-1', 'cook.cs-1'), JSON.stringify(cachedSession));

    const getSpy = jest.spyOn(api, 'GET');

    // Network failure (status 0) falls back to user-1 cache
    getSpy.mockRejectedValueOnce(new Error('offline'));
    const { result: offRes, qc: offQc } = await renderWithHookCook('cs-1');
    await waitFor(() => expect(offRes.current.data?.id).toBe('cs-1'));
    offQc.clear();

    // 401 NEVER falls back to cached session even when cache exists
    getSpy.mockResolvedValueOnce(errRes(401, { code: 'unauthenticated' }) as never);
    const { result: authErrRes, qc: authErrQc } = await renderWithHookCook('cs-1');
    await waitFor(() => expect(authErrRes.current.isError).toBe(true));
    expect(authErrRes.current.data).toBeUndefined();
    authErrQc.clear();

    // Switching to user-2 on offline error does NOT leak user-1 cached session
    mockSessionState.user = { id: 'user-2', email: 'u2@example.vn', role: 'user', onboarding_completed: true };
    getSpy.mockRejectedValueOnce(new Error('offline'));
    const { result: u2Res, qc: u2Qc } = await renderWithHookCook('cs-1');
    await waitFor(() => expect(u2Res.current.isError).toBe(true));
    expect(u2Res.current.data).toBeUndefined();
    u2Qc.clear();
  });

  it('nau-xong/[id] checks reverted before stale result and clearCompleteOutcome removes RESULT(id)', async () => {
    mockNavState.params = { id: 'cs-rev' };
    await AsyncStorage.setItem(
      getScopedKey('user-1', 'complete.cs-rev'),
      JSON.stringify({
        state: 'done',
        result: {
          cook_session: { id: 'cs-rev', status: 'completed', undo_deadline: '2099-01-01T00:00:00Z' },
          deductions: [],
          shortfalls: [],
        },
      }),
    );

    jest.spyOn(api, 'GET').mockImplementation(async (path: string) => {
      if (path === '/cook-sessions/{id}') {
        return okRes({
          id: 'cs-rev',
          meal_plan_id: 'mp-1',
          status: 'reverted',
          started_at: '2026-11-24T10:00:00Z',
          schedule: [],
        }) as never;
      }
      if (path === '/meal-plans/{id}') return okRes({ id: 'mp-1', items: [] }) as never;
      if (path === '/catalog/snapshot') return okRes({ ingredients: [], recipes: [] }) as never;
      return okRes({}) as never;
    });

    await renderWithProviders(<Finished />);
    expect(await screen.findByTestId('screen-reverted')).toBeTruthy();

    await clearCompleteOutcome('cs-rev', 'user-1');
    expect(await getCompleteOutcome('cs-rev', 'user-1')).toBeNull();
  });

  it('reuses key for identical body, rotates for changed body, and resets on idem.reset()', async () => {
    const { result } = await renderHook(() => useIdempotencyKey());

    let k1 = '';
    let k1Repeat = '';
    let k2 = '';
    let k1AfterReset = '';

    await act(async () => {
      k1 = result.current.keyFor({ meal: 'lunch', persons: 2 });
      k1Repeat = result.current.keyFor({ meal: 'lunch', persons: 2 });
    });
    expect(k1Repeat).toBe(k1);

    await act(async () => {
      k2 = result.current.keyFor({ meal: 'lunch', persons: 3 });
    });
    expect(k2).not.toBe(k1);

    await act(async () => {
      result.current.reset();
      k1AfterReset = result.current.keyFor({ meal: 'lunch', persons: 2 });
    });
    expect(k1AfterReset).not.toBe(k1);
    expect(k1AfterReset).not.toBe(k2);
  });
});
