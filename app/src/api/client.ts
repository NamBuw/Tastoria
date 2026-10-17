import Constants from 'expo-constants';
import createClient from 'openapi-fetch';
import { Platform } from 'react-native';

import { loadRefresh, saveRefresh } from '@/auth/tokenStore';

import type { components, paths } from './schema';

export type Schemas = components['schemas'];
export type Problem = Schemas['Problem'] & Record<string, unknown>;
export type AuthSession = Schemas['AuthSession'];

/** Base URL of the API (`/api/v1` on the same origin when the web app is served by nginx). */
export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? (Platform.OS === 'web' ? '/api/v1' : '')).replace(/\/$/, '');
export const APP_VERSION = Constants.expoConfig?.version ?? '0.0.0';

// ---- tokens -------------------------------------------------------------------------------------

let accessToken: string | null = null;
let refreshToken: string | null = null;
let refreshing: Promise<AuthSession | null> | null = null;
const listeners = new Set<(s: AuthSession | null) => void>();

/** Called by the auth provider: every new session (login, refresh) and sign-out (null). */
export function onSessionChange(fn: (s: AuthSession | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export async function setSession(s: AuthSession | null): Promise<void> {
  accessToken = s?.access_token ?? null;
  refreshToken = s?.refresh_token ?? null;
  await saveRefresh(refreshToken);
  listeners.forEach((fn) => fn(s));
}

export function currentRefreshToken(): string | null {
  return refreshToken;
}

/** One refresh at a time; concurrent 401s wait for the same promise (NFR-SEC-01 rotation). */
export async function refreshSession(): Promise<AuthSession | null> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const token = refreshToken ?? (await loadRefresh());
    if (!token) return null;
    try {
      const res = await fetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-App-Version': APP_VERSION },
        body: JSON.stringify({ refresh_token: token }),
      });
      if (res.ok) {
        const s = (await res.json()) as AuthSession;
        await setSession(s);
        return s;
      }
      if (res.status === 401 || res.status === 403) await setSession(null);
      return null;
    } catch {
      // offline: keep the refresh token for later
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

function withHeaders(req: Request): Request {
  const r = new Request(req);
  r.headers.set('X-App-Version', APP_VERSION);
  if (accessToken && !r.headers.has('Authorization')) r.headers.set('Authorization', `Bearer ${accessToken}`);
  return r;
}

async function authFetch(input: Request): Promise<Response> {
  const retry = input.clone();
  const res = await fetch(withHeaders(input));
  if (res.status !== 401 || input.url.includes('/auth/')) return res;
  const body = (await res.clone().json().catch(() => null)) as Problem | null;
  if (body?.code !== 'unauthenticated' && body?.code !== 'token_revoked') return res;
  const s = await refreshSession();
  if (!s) return res;
  return fetch(withHeaders(retry));
}

export const api = createClient<paths>({ baseUrl: API_URL, fetch: authFetch });

// ---- result handling ----------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    public problem: Problem | null,
  ) {
    super(problem?.code ?? `http_${status}`);
  }
  get code(): string {
    return this.problem?.code ?? (this.status === 0 ? 'network' : `http_${this.status}`);
  }
}

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

/** Unwraps an openapi-fetch result: returns data or throws ApiError (status 0 = no network). */
export async function call<T>(p: Promise<FetchResult<T>>): Promise<T> {
  let r: FetchResult<T>;
  try {
    r = await p;
  } catch {
    throw new ApiError(0, null);
  }
  if (r.response.ok) return r.data as T;
  const err = r.error as Problem | undefined;
  throw new ApiError(r.response.status, err && typeof err === 'object' && 'code' in err ? err : null);
}

export function isCode(e: unknown, ...codes: string[]): e is ApiError {
  return e instanceof ApiError && codes.includes(e.code);
}

/** Untyped request through the same auth/refresh path; used by the outbox, which stores plain JSON. */
export async function rawRequest(
  method: string,
  path: string,
  body: unknown,
  headers: Record<string, string> = {},
): Promise<{ status: number; json: unknown }> {
  const req = new Request(`${API_URL}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const res = await authFetch(req);
  const json = await res.json().catch(() => null);
  return { status: res.status, json };
}
