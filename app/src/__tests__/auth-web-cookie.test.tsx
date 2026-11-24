import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react-native';
import React from 'react';
import { Platform } from 'react-native';

import { loadRefresh, saveRefresh } from '@/auth/tokenStore.web';

jest.unmock('@/auth/session');

process.env.EXPO_PUBLIC_API_URL = 'http://localhost/api/v1';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const apiClient = require('@/api/client') as typeof import('@/api/client');
const { bumpSessionEpoch, ensureAuthChannel, getCurrentUserId, getSessionEpoch, rawRequest, refreshSession, setSession } = apiClient;
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { SessionProvider, useSession } = require('@/auth/session') as typeof import('@/auth/session');

describe('Web HttpOnly cookie auth (Contract #1)', () => {
  const originalPlatform = Platform.OS;
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    Object.defineProperty(Platform, 'OS', { value: 'web', configurable: true });
  });

  afterEach(async () => {
    globalThis.fetch = originalFetch;
    Object.defineProperty(Platform, 'OS', { value: originalPlatform, configurable: true });
    jest.restoreAllMocks();
    await act(async () => {
      await setSession(null);
    });
  });

  it('tokenStore.web never reads or writes sessionStorage or localStorage', async () => {
    const getItemSpy = jest.fn(() => 'stale-token');
    const setItemSpy = jest.fn();
    const removeItemSpy = jest.fn();
    const origSessionStorage = (globalThis as unknown as { sessionStorage?: unknown }).sessionStorage;
    const origLocalStorage = (globalThis as unknown as { localStorage?: unknown }).localStorage;

    Object.defineProperty(globalThis, 'sessionStorage', {
      value: { getItem: getItemSpy, setItem: setItemSpy, removeItem: removeItemSpy },
      configurable: true,
    });
    Object.defineProperty(globalThis, 'localStorage', {
      value: { getItem: getItemSpy, setItem: setItemSpy, removeItem: removeItemSpy },
      configurable: true,
    });

    try {
      await saveRefresh('secret-refresh-token');
      const loaded = await loadRefresh();
      expect(loaded).toBeNull();
      expect(getItemSpy).not.toHaveBeenCalled();
      expect(setItemSpy).not.toHaveBeenCalled();
      expect(removeItemSpy).not.toHaveBeenCalled();
    } finally {
      Object.defineProperty(globalThis, 'sessionStorage', { value: origSessionStorage, configurable: true });
      Object.defineProperty(globalThis, 'localStorage', { value: origLocalStorage, configurable: true });
    }
  });

  it('refreshSession sends X-Client-Platform: web and credentials: include even when refreshToken is null', async () => {
    const fetchMock = jest.fn(async () =>
      new Response(
        JSON.stringify({
          access_token: 'acc-new',
          refresh_token: null,
          token_type: 'bearer',
          expires_in: 900,
          user: { id: 'u-1', email: 'web@tastoria.vn', role: 'user', onboarding_completed: true },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const session = await refreshSession();
    expect(session?.access_token).toBe('acc-new');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/auth/refresh');
    expect(init.credentials).toBe('include');
    expect((init.headers as Record<string, string>)['X-Client-Platform']).toBe('web');
    expect(init.body).toBe('{}');
  });

  it('signOut(false) on web calls /auth/logout with X-Client-Platform: web and credentials: include even when refresh_token is null', async () => {
    const calls: { url: string; credentials: string | undefined; platform: string | null }[] = [];
    globalThis.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (input instanceof Request) {
        calls.push({
          url: input.url,
          credentials: input.credentials,
          platform: input.headers.get('X-Client-Platform'),
        });
        if (input.url.includes('/auth/logout')) {
          return new Response(null, { status: 204 });
        }
      } else {
        const headers = init?.headers as Record<string, string> | undefined;
        calls.push({
          url: String(input),
          credentials: init?.credentials,
          platform: headers?.['X-Client-Platform'] ?? null,
        });
        if (String(input).includes('/auth/refresh')) {
          return new Response(
            JSON.stringify({
              access_token: 'acc-web',
              refresh_token: null,
              token_type: 'bearer',
              expires_in: 900,
              user: { id: 'u-1', email: 'web@tastoria.vn', role: 'user', onboarding_completed: true },
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
      }
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
    }) as unknown as typeof fetch;

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>
        <SessionProvider>{children}</SessionProvider>
      </QueryClientProvider>
    );

    const { result } = await renderHook(() => useSession(), { wrapper });
    await waitFor(() => {
      expect(result.current.status).toBe('signedIn');
    });
    await act(async () => {
      await result.current.signOut(false);
    });

    const logoutCall = calls.find((c) => c.url.includes('/auth/logout'));
    expect(logoutCall).toBeDefined();
    expect(logoutCall?.platform).toBe('web');
    expect(logoutCall?.credentials).toBe('include');
    expect(result.current.status).toBe('signedOut');
  });

  it('refreshSession and authFetch cancel res.body on non-OK / retried 401 responses without failing when body is undefined', async () => {
    const cancelRefresh = jest.fn(async () => {});
    const res401 = new Response(JSON.stringify({ code: 'refresh_invalid' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
    Object.defineProperty(res401, 'body', {
      value: { cancel: cancelRefresh },
      configurable: true,
    });

    globalThis.fetch = jest.fn(async () => res401) as unknown as typeof fetch;
    const failed = await refreshSession();
    expect(failed).toBeNull();
    expect(cancelRefresh).toHaveBeenCalledTimes(1);

    // Also works cleanly when mock Response has undefined body
    const resNoBody = {
      ok: false,
      status: 401,
      body: undefined,
    } as unknown as Response;
    globalThis.fetch = jest.fn(async () => resNoBody) as unknown as typeof fetch;
    await expect(refreshSession()).resolves.toBeNull();

    // authFetch cancels the discarded 401 response body before retrying after refreshSession succeeds
    const cancelAuth401 = jest.fn(async () => {});
    let attempt = 0;
    globalThis.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/auth/refresh')) {
        return new Response(
          JSON.stringify({
            access_token: 'acc-refreshed',
            refresh_token: null,
            token_type: 'bearer',
            expires_in: 900,
            user: { id: 'u-1', email: 'web@tastoria.vn', role: 'user', onboarding_completed: true },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      attempt += 1;
      if (attempt === 1) {
        const firstRes = new Response(JSON.stringify({ code: 'unauthenticated' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        });
        Object.defineProperty(firstRes, 'body', {
          value: { cancel: cancelAuth401 },
          configurable: true,
        });
        return firstRes;
      }
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }) as unknown as typeof fetch;

    const retryResult = await rawRequest('GET', '/pantry/lots', undefined);
    expect(retryResult).toEqual({ status: 200, json: { ok: true } });
    expect(cancelAuth401).toHaveBeenCalledTimes(1);
  });

  it('coordinates web refresh via navigator.locks and BroadcastChannel without failing when unavailable', async () => {
    const channels: MockBC[] = [];
    class MockBC {
      name: string;
      onmessage: ((ev: MessageEvent) => void) | null = null;
      posted: unknown[] = [];
      constructor(name: string) {
        this.name = name;
        channels.push(this);
      }
      postMessage(msg: unknown) {
        this.posted.push(msg);
      }
      close() {}
    }

    const origBC = (globalThis as unknown as { BroadcastChannel?: unknown }).BroadcastChannel;
    const lockReq = jest.fn(async (_name: string, fn: () => Promise<unknown>) => fn());
    const origLocks = (navigator as unknown as { locks?: unknown }).locks;

    Object.defineProperty(globalThis, 'BroadcastChannel', { value: MockBC, configurable: true });
    Object.defineProperty(navigator, 'locks', { value: { request: lockReq }, configurable: true });

    try {
      const ch = ensureAuthChannel();
      expect(ch).toBeTruthy();

      globalThis.fetch = jest.fn(async () =>
        new Response(
          JSON.stringify({
            access_token: 'acc-locked',
            refresh_token: null,
            token_type: 'bearer',
            expires_in: 900,
            user: { id: 'u-lock', email: 'lock@example.vn', role: 'user', onboarding_completed: true },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ) as unknown as typeof fetch;

      const s = await refreshSession();
      expect(s?.access_token).toBe('acc-locked');
      expect(lockReq).toHaveBeenCalledWith('tastoria-auth-refresh', expect.any(Function));
      expect(channels[0].posted.some((m) => (m as { type?: string }).type === 'session')).toBe(true);

      // Incoming signed_out message from another tab clears local session
      channels[0].onmessage?.({
        data: { type: 'signed_out', sender: 'other-tab', ts: Date.now() },
      } as MessageEvent);
      await waitFor(() => {
        expect(getCurrentUserId()).toBeNull();
      });

      // Fallback cleanly when navigator.locks is unavailable
      Object.defineProperty(navigator, 'locks', { value: undefined, configurable: true });
      const fallbackSession = await refreshSession();
      expect(fallbackSession?.access_token).toBe('acc-locked');
    } finally {
      Object.defineProperty(globalThis, 'BroadcastChannel', { value: origBC, configurable: true });
      Object.defineProperty(navigator, 'locks', { value: origLocks, configurable: true });
    }
  });

  it('retries 409 refresh_retry_conflict with bounded backoff and keeps existing session if exhausted', async () => {
    const mkSess = (id: string, email: string, token: string) => ({
      access_token: token,
      refresh_token: null,
      token_type: 'Bearer' as const,
      expires_in: 900 as const,
      refresh_expires_at: '2026-12-01T00:00:00Z',
      user: { id, email, role: 'user' as const, status: 'active' as const, created_at: '2026-11-01T00:00:00Z' },
    });
    await setSession(mkSess('u-409', 'u409@example.vn', 'acc-existing'));

    let callCount = 0;
    globalThis.fetch = jest.fn(async () => {
      callCount += 1;
      if (callCount === 1) {
        return new Response(JSON.stringify({ code: 'refresh_retry_conflict' }), {
          status: 409,
          headers: { 'Content-Type': 'application/json', 'Retry-After': '0.1' },
        });
      }
      return new Response(
        JSON.stringify({
          access_token: 'acc-after-409',
          refresh_token: null,
          token_type: 'bearer',
          expires_in: 900,
          user: { id: 'u-409', email: 'u409@example.vn', role: 'user', onboarding_completed: true },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }) as unknown as typeof fetch;

    const recovered = await refreshSession();
    expect(callCount).toBe(2);
    expect(recovered?.access_token).toBe('acc-after-409');

    // Persistent 409 exhausts retries (1 + 3 = 4 attempts) WITHOUT clearing current session
    let exhaustCount = 0;
    globalThis.fetch = jest.fn(async () => {
      exhaustCount += 1;
      return new Response(JSON.stringify({ code: 'refresh_retry_conflict' }), {
        status: 409,
        headers: { 'Content-Type': 'application/json', 'Retry-After': '0.1' },
      });
    }) as unknown as typeof fetch;

    const exhausted = await refreshSession();
    expect(exhaustCount).toBe(4);
    expect(exhausted).toBeNull();
    expect(getCurrentUserId()).toBe('u-409');
  });

  it('authFetch skips refreshSession on 401 when accessToken already changed since usedToken', async () => {
    const mkRaceSess = (token: string) => ({
      access_token: token,
      refresh_token: null,
      token_type: 'Bearer' as const,
      expires_in: 900 as const,
      refresh_expires_at: '2026-12-01T00:00:00Z',
      user: { id: 'u-race', email: 'race@example.vn', role: 'user' as const, status: 'active' as const, created_at: '2026-11-01T00:00:00Z' },
    });
    await setSession(mkRaceSess('tok-stale'));

    let refreshHits = 0;
    let lotHits = 0;
    globalThis.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const req = input instanceof Request ? input : new Request(String(input));
      if (req.url.includes('/auth/refresh')) {
        refreshHits += 1;
        return new Response('{}', { status: 401 });
      }
      lotHits += 1;
      if (lotHits === 1) {
        expect(req.headers.get('Authorization')).toBe('Bearer tok-stale');
        // Concurrent session update lands before 401 handler checks accessToken !== usedToken
        await setSession(mkRaceSess('tok-fresh'));
        return new Response(JSON.stringify({ code: 'unauthenticated' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      expect(req.headers.get('Authorization')).toBe('Bearer tok-fresh');
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }) as unknown as typeof fetch;

    const result = await rawRequest('GET', '/pantry/lots', undefined);
    expect(result).toEqual({ status: 200, json: { ok: true } });
    expect(lotHits).toBe(2);
    expect(refreshHits).toBe(0);
  });

  it('discards stale in-flight refreshSession result when sessionEpoch changes via signOut or user switch', async () => {
    let resolveFetch!: (r: Response) => void;
    globalThis.fetch = jest.fn(
      () =>
        new Promise<Response>((res) => {
          resolveFetch = res;
        }),
    ) as unknown as typeof fetch;

    const epochBefore = getSessionEpoch();
    const pendingRefresh = refreshSession();

    // User switches / signs out while refresh is in-flight
    await setSession({
      access_token: 'acc-user-b',
      refresh_token: null,
      token_type: 'Bearer',
      expires_in: 900,
      refresh_expires_at: '2026-12-01T00:00:00Z',
      user: { id: 'user-b', email: 'b@example.vn', role: 'user', status: 'active', created_at: '2026-11-01T00:00:00Z' },
    });
    expect(getSessionEpoch()).toBeGreaterThan(epochBefore);
    bumpSessionEpoch();

    resolveFetch(
      new Response(
        JSON.stringify({
          access_token: 'acc-user-a-stale',
          refresh_token: null,
          token_type: 'bearer',
          expires_in: 900,
          user: { id: 'user-a', email: 'a@example.vn', role: 'user', onboarding_completed: true },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const out = await pendingRefresh;
    expect(out).toBeNull();
    expect(getCurrentUserId()).toBe('user-b');
  });
});
