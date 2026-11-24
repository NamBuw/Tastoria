import Constants from 'expo-constants';
import createClient from 'openapi-fetch';
import { Platform } from 'react-native';

import { loadRefresh, saveRefresh } from '@/auth/tokenStore';

import type { components, paths } from './schema';

export type Schemas = components['schemas'];
type Problem = Schemas['Problem'] & Record<string, unknown>;
export type AuthSession = Omit<Schemas['AuthSession'], 'refresh_token'> & {
  refresh_token?: string | null;
};

/** Base URL of the API (`/api/v1` on the same origin when the web app is served by nginx). */
export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? (Platform.OS === 'web' ? '/api/v1' : '')).replace(/\/$/, '');
const APP_VERSION = Constants.expoConfig?.version ?? '0.0.0';

// ---- tokens & cross-tab sync --------------------------------------------------------------------

let currentSession: AuthSession | null = null;
let accessToken: string | null = null;
let refreshToken: string | null = null;
let refreshing: Promise<AuthSession | null> | null = null;
let sessionEpoch = 0;
let lastBroadcastSessionAt = 0;
const listeners = new Set<(s: AuthSession | null) => void>();

const TAB_ID =
  typeof globalThis.crypto?.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : `tab-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;

type AuthBroadcastMsg =
  | { type: 'session'; sender: string; session: AuthSession; ts: number }
  | { type: 'signed_out'; sender: string; ts: number };

let authChannel: BroadcastChannel | null = null;
let authChannelCtor: unknown = null;

function handleAuthMessage(ev: MessageEvent<AuthBroadcastMsg>) {
  const msg = ev.data;
  if (!msg || typeof msg !== 'object' || msg.sender === TAB_ID) return;
  if (msg.type === 'session' && msg.session?.access_token) {
    lastBroadcastSessionAt = Math.max(lastBroadcastSessionAt, msg.ts || Date.now());
    void applySession(msg.session, { broadcast: false });
  } else if (msg.type === 'signed_out') {
    void applySession(null, { broadcast: false });
  }
}

export function ensureAuthChannel(): BroadcastChannel | null {
  if (Platform.OS !== 'web' || typeof BroadcastChannel === 'undefined') {
    return null;
  }
  if (authChannel && authChannelCtor === BroadcastChannel) {
    return authChannel;
  }
  if (authChannel) {
    try {
      authChannel.close();
    } catch {
      // ignore
    }
    authChannel = null;
  }
  try {
    authChannel = new BroadcastChannel('tastoria-auth');
    authChannelCtor = BroadcastChannel;
    authChannel.onmessage = handleAuthMessage;
    return authChannel;
  } catch {
    authChannel = null;
    authChannelCtor = null;
    return null;
  }
}

function postAuthBroadcast(msg: AuthBroadcastMsg) {
  const ch = ensureAuthChannel();
  if (!ch) return;
  try {
    ch.postMessage(msg);
  } catch {
    // ignore closed channel
  }
}

/** Monotonic epoch bumped on sign-in, register, sign-out, and session transitions. */
export function bumpSessionEpoch(): number {
  sessionEpoch += 1;
  return sessionEpoch;
}

export function getSessionEpoch(): number {
  return sessionEpoch;
}

export function getCurrentUserId(): string | null {
  return currentSession?.user?.id ?? null;
}

/** Called by the auth provider: every new session (login, refresh) and sign-out (null). */
export function onSessionChange(fn: (s: AuthSession | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

async function applySession(s: AuthSession | null, opts: { broadcast?: boolean } = {}): Promise<void> {
  sessionEpoch += 1;
  currentSession = s;
  accessToken = s?.access_token ?? null;
  refreshToken = s?.refresh_token ?? null;
  await saveRefresh(Platform.OS === 'web' ? null : refreshToken);
  if (opts.broadcast !== false) {
    postAuthBroadcast(
      s
        ? { type: 'session', sender: TAB_ID, session: s, ts: Date.now() }
        : { type: 'signed_out', sender: TAB_ID, ts: Date.now() },
    );
  }
  listeners.forEach((fn) => fn(s));
}

export async function setSession(s: AuthSession | null): Promise<void> {
  await applySession(s, { broadcast: true });
}

export function currentRefreshToken(): string | null {
  return refreshToken;
}

async function withRefreshLock<T>(fn: () => Promise<T>): Promise<T> {
  if (
    Platform.OS === 'web' &&
    typeof navigator !== 'undefined' &&
    navigator.locks &&
    typeof navigator.locks.request === 'function'
  ) {
    return navigator.locks.request('tastoria-auth-refresh', fn);
  }
  return fn();
}

function parseRetryAfterMs(res: Response, fallbackMs: number): number {
  const raw = res.headers?.get?.('Retry-After');
  if (!raw) return fallbackMs;
  const sec = Number(raw);
  if (Number.isFinite(sec) && sec > 0) {
    return Math.min(1500, Math.max(100, Math.round(sec * 1000)));
  }
  return fallbackMs;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const MAX_CONFLICT_RETRIES = 3;

/**
 * One refresh at a time across tabs (Web Locks + BroadcastChannel) and inside this tab;
 * guards against stale epoch resurrection and handles transient 409 refresh_retry_conflict cleanly.
 */
export async function refreshSession(): Promise<AuthSession | null> {
  if (refreshing) return refreshing;
  ensureAuthChannel();
  const startEpoch = sessionEpoch;
  const tokenBeforeStart = accessToken;
  const userIdBeforeStart = currentSession?.user?.id ?? null;
  const startTs = Date.now();

  refreshing = withRefreshLock(async () => {
    // Another tab may have broadcast a fresh session while we waited on the Web Lock.
    if (
      currentSession &&
      accessToken &&
      accessToken !== tokenBeforeStart &&
      lastBroadcastSessionAt >= startTs &&
      (!userIdBeforeStart || currentSession.user.id === userIdBeforeStart)
    ) {
      return currentSession;
    }
    if (sessionEpoch !== startEpoch) {
      return null;
    }

    const isWeb = Platform.OS === 'web';
    const token = isWeb ? refreshToken : (refreshToken ?? (await loadRefresh()));
    if (!isWeb && !token) return null;

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-App-Version': APP_VERSION,
    };
    if (isWeb) headers['X-Client-Platform'] = 'web';

    try {
      for (let attempt = 0; attempt <= MAX_CONFLICT_RETRIES; attempt += 1) {
        if (
          currentSession &&
          accessToken &&
          accessToken !== tokenBeforeStart &&
          lastBroadcastSessionAt >= startTs &&
          (!userIdBeforeStart || currentSession.user.id === userIdBeforeStart)
        ) {
          return currentSession;
        }
        if (sessionEpoch !== startEpoch) {
          return null;
        }

        const res = await fetch(`${API_URL}/auth/refresh`, {
          method: 'POST',
          headers,
          ...(isWeb ? { credentials: 'include' as RequestCredentials } : {}),
          body: JSON.stringify(token ? { refresh_token: token } : {}),
        });

        if (res.ok) {
          const s = (await res.json()) as AuthSession;
          if (sessionEpoch !== startEpoch) {
            if (
              currentSession &&
              lastBroadcastSessionAt >= startTs &&
              currentSession.user.id === s.user.id
            ) {
              return currentSession;
            }
            return null;
          }
          await setSession(s);
          return s;
        }

        if (res.status === 409) {
          const prob = (await res.json().catch(() => null)) as Problem | null;
          if (!prob) await res.body?.cancel().catch(() => {});
          if (
            currentSession &&
            accessToken &&
            accessToken !== tokenBeforeStart &&
            lastBroadcastSessionAt >= startTs &&
            (!userIdBeforeStart || currentSession.user.id === userIdBeforeStart)
          ) {
            return currentSession;
          }
          if (attempt < MAX_CONFLICT_RETRIES && (!prob?.code || prob.code === 'refresh_retry_conflict')) {
            const backoff = parseRetryAfterMs(res, 150 * 2 ** attempt);
            await sleep(backoff);
            continue;
          }
          // Exhausted bounded 409 retries: return null WITHOUT clearing the current session.
          return null;
        }

        await res.body?.cancel().catch(() => {});
        if ((res.status === 401 || res.status === 403) && sessionEpoch === startEpoch) {
          await setSession(null);
        }
        return null;
      }
      return null;
    } catch {
      // offline: keep the refresh token for later
      return null;
    }
  }).finally(() => {
    refreshing = null;
  });
  return refreshing;
}

function withHeaders(req: Request): Request {
  const isWeb = Platform.OS === 'web';
  const r = isWeb ? new Request(req, { credentials: 'include' }) : new Request(req);
  r.headers.set('X-App-Version', APP_VERSION);
  if (isWeb) r.headers.set('X-Client-Platform', 'web');
  if (accessToken && !r.headers.has('Authorization')) r.headers.set('Authorization', `Bearer ${accessToken}`);
  return r;
}

const SKIP_REFRESH_AUTH_RE = /\/auth\/(login|register|refresh|logout|logout-all|password-reset|verify-email\/confirm)\b/;

async function authFetch(input: Request): Promise<Response> {
  const retry = input.clone();
  const usedToken = accessToken;
  const res = await fetch(withHeaders(input));
  if (res.status !== 401 || SKIP_REFRESH_AUTH_RE.test(input.url)) return res;
  const body = (await res.clone().json().catch(() => null)) as Problem | null;
  if (body?.code !== 'unauthenticated' && body?.code !== 'token_revoked') return res;

  // Another concurrent call or tab already updated accessToken since this request started.
  if (accessToken && accessToken !== usedToken) {
    void res.body?.cancel().catch(() => {});
    return fetch(withHeaders(retry));
  }

  const s = await refreshSession();
  if (!s) return res;
  void res.body?.cancel().catch(() => {});
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
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') throw e;
    throw new ApiError(0, null);
  }
  if (!r || !r.response) throw new ApiError(0, null);
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
