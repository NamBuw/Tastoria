import AsyncStorage from '@react-native-async-storage/async-storage';
import { AppState } from 'react-native';

import { getCurrentUserId, onSessionChange, rawRequest, type Schemas } from '@/api/client';
import { uuid } from './ids';
import { getScopedKey, registerUserCachePurge } from './storage';

/**
 * User-scoped outbox for writes that must survive a lost connection (UC20 3a, UC15 14a):
 * "nấu xong" (POST /cook-sessions/{id}/complete with a fixed Idempotency-Key) and interaction events
 * (POST /events, de-duplicated by event_id).
 *
 * Guarantees:
 * - Storage keys and entries are strictly scoped by userId (never flushed under another user's token).
 * - All AsyncStorage reads/writes are serialized via a per-user promise queue.
 * - flush() merge-removes only processed entry IDs instead of overwriting snapshots.
 * - 401 pauses the user's queue and keeps entries intact until re-authentication.
 */
type Entry = {
  id: string;
  userId: string;
  kind: 'complete' | 'events';
  method: 'POST';
  path: string;
  body: unknown;
  idempotencyKey?: string;
  sessionId?: string;
  createdAt: string;
  attempts: number;
};

export type CompleteOutcome =
  | { state: 'pending'; authRequired?: boolean }
  | { state: 'done'; result: Schemas['CookCompletion'] }
  | { state: 'failed'; status: number; problem: unknown };

const MAX_QUEUE_SIZE = 100;
const MAX_RETRY_ATTEMPTS = 10;

const KEY = (userId: string) => getScopedKey(userId, 'outbox.v1');
const RESULT = (userId: string, sessionId: string) => getScopedKey(userId, `complete.${sessionId}`);

const userQueues = new Map<string, Promise<unknown>>();
const flushingByUser = new Map<string, Promise<void>>();
const pausedForAuth = new Set<string>();
const listeners = new Set<() => void>();
let outboxStarted = false;

registerUserCachePurge((userId) => {
  pausedForAuth.delete(userId);
});

onSessionChange((s) => {
  const uid = s?.user?.id;
  if (uid) {
    const wasPaused = pausedForAuth.delete(uid);
    if (outboxStarted || wasPaused) {
      void flush(uid);
    }
  }
});

function enqueueLock<T>(userId: string, task: () => Promise<T>): Promise<T> {
  const prev = userQueues.get(userId) ?? Promise.resolve();
  const next = prev.catch(() => undefined).then(task);
  const tail = next.then(
    () => undefined,
    () => undefined,
  );
  userQueues.set(userId, tail);
  next.finally(() => {
    if (userQueues.get(userId) === tail) userQueues.delete(userId);
  });
  return next;
}

async function read(userId: string): Promise<Entry[]> {
  try {
    const raw = await AsyncStorage.getItem(KEY(userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e): e is Entry => Boolean(e && typeof e.id === 'string' && (!e.userId || e.userId === userId)),
    );
  } catch {
    return [];
  }
}

async function write(userId: string, entries: Entry[]): Promise<void> {
  try {
    await AsyncStorage.setItem(KEY(userId), JSON.stringify(entries));
  } catch {
    // storage unavailable
  }
}

function capQueue(entries: Entry[]): Entry[] {
  if (entries.length <= MAX_QUEUE_SIZE) return entries;
  const next = [...entries];
  while (next.length > MAX_QUEUE_SIZE) {
    const evIdx = next.findIndex((x) => x.kind === 'events');
    if (evIdx >= 0) next.splice(evIdx, 1);
    else next.shift();
  }
  return next;
}

export function onOutboxChange(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  listeners.forEach((fn) => fn());
}

/** Queue "nấu xong" once per session; a second tap reuses the queued entry and its key. */
export async function enqueueComplete(
  sessionId: string,
  body: Schemas['CookCompleteRequest'],
  userId?: string | null,
): Promise<void> {
  const uid = userId ?? getCurrentUserId();
  if (!uid) return;
  await enqueueLock(uid, async () => {
    const entries = await read(uid);
    if (!entries.some((e) => e.kind === 'complete' && e.sessionId === sessionId)) {
      entries.push({
        id: uuid(),
        userId: uid,
        kind: 'complete',
        method: 'POST',
        path: `/cook-sessions/${sessionId}/complete`,
        body,
        idempotencyKey: uuid(),
        sessionId,
        createdAt: new Date().toISOString(),
        attempts: 0,
      });
      await write(uid, capQueue(entries));
      await AsyncStorage.setItem(RESULT(uid, sessionId), JSON.stringify({ state: 'pending' })).catch(() => {});
    }
  });
  await flush(uid);
}

export async function getCompleteOutcome(sessionId: string, userId?: string | null): Promise<CompleteOutcome | null> {
  const uid = userId ?? getCurrentUserId();
  if (!uid) return null;
  try {
    const raw = await AsyncStorage.getItem(RESULT(uid, sessionId));
    return raw ? (JSON.parse(raw) as CompleteOutcome) : null;
  } catch {
    return null;
  }
}

export async function clearCompleteOutcome(sessionId: string, userId?: string | null): Promise<void> {
  const uid = userId ?? getCurrentUserId();
  if (!uid) return;
  await enqueueLock(uid, async () => {
    await AsyncStorage.removeItem(RESULT(uid, sessionId)).catch(() => {});
  });
  notify();
}

export async function enqueueEvents(
  events: Omit<Schemas['InteractionEvent'], 'event_id' | 'occurred_at'>[],
  userId?: string | null,
) {
  if (!events.length) return;
  const uid = userId ?? getCurrentUserId();
  if (!uid) return;
  const now = new Date().toISOString();
  await enqueueLock(uid, async () => {
    const entries = await read(uid);
    entries.push({
      id: uuid(),
      userId: uid,
      kind: 'events',
      method: 'POST',
      path: '/events',
      body: { events: events.map((e) => ({ ...e, event_id: uuid(), occurred_at: now })) },
      createdAt: now,
      attempts: 0,
    });
    await write(uid, capQueue(entries));
  });
  void flush(uid);
}

function retryable(status: number, problem: unknown): boolean {
  if (status === 0 || status >= 500 || status === 429) return true;
  const code = (problem as { code?: string } | null)?.code;
  return status === 409 && code === 'idempotency_in_progress';
}

export function isOutboxPausedForAuth(userId?: string | null): boolean {
  const uid = userId ?? getCurrentUserId();
  return uid ? pausedForAuth.has(uid) : false;
}

export function flush(userId?: string | null): Promise<void> {
  const activeUid = getCurrentUserId();
  const uid = userId ?? activeUid;
  if (!uid) return Promise.resolve();
  // Cross-account isolation guard: never flush User A's queue under User B's active token.
  if (activeUid && uid !== activeUid) return Promise.resolve();
  if (pausedForAuth.has(uid)) return Promise.resolve();

  const existing = flushingByUser.get(uid);
  if (existing) return existing;

  const task = (async () => {
    const snapshot = await enqueueLock(uid, () => read(uid));
    if (!snapshot.length) return;

    for (const e of snapshot) {
      const currentUid = getCurrentUserId();
      if ((currentUid && currentUid !== uid) || (e.userId && e.userId !== uid) || pausedForAuth.has(uid)) {
        break;
      }

      let status = 0;
      let json: unknown = null;
      try {
        ({ status, json } = await rawRequest(
          e.method,
          e.path,
          e.body,
          e.idempotencyKey ? { 'Idempotency-Key': e.idempotencyKey } : {},
        ));
      } catch {
        status = 0;
      }

      if (status === 401) {
        pausedForAuth.add(uid);
        await enqueueLock(uid, async () => {
          if (e.kind === 'complete' && e.sessionId) {
            await AsyncStorage.setItem(
              RESULT(uid, e.sessionId),
              JSON.stringify({ state: 'pending', authRequired: true } satisfies CompleteOutcome),
            ).catch(() => {});
          }
        });
        break;
      }

      const nextAttempts = e.attempts + 1;
      const shouldDrop =
        (status !== 0 && !retryable(status, json)) || (status !== 0 && nextAttempts >= MAX_RETRY_ATTEMPTS);

      await enqueueLock(uid, async () => {
        const latest = await read(uid);
        if (shouldDrop) {
          const merged = latest.filter((x) => x.id !== e.id);
          await write(uid, merged);
          if (e.kind === 'complete' && e.sessionId) {
            const outcome: CompleteOutcome =
              status >= 200 && status < 300
                ? { state: 'done', result: json as Schemas['CookCompletion'] }
                : { state: 'failed', status, problem: json };
            await AsyncStorage.setItem(RESULT(uid, e.sessionId), JSON.stringify(outcome)).catch(() => {});
          }
        } else {
          const merged = latest.map((x) => (x.id === e.id ? { ...x, attempts: nextAttempts } : x));
          await write(uid, merged);
        }
      });

      if (status === 0) break; // offline: keep order, try again later
    }

    notify();
  })().finally(() => {
    flushingByUser.delete(uid);
  });

  flushingByUser.set(uid, task);
  return task;
}

/** Retry every 20 s and whenever the app comes back to the foreground. */
export function startOutbox(): () => void {
  outboxStarted = true;
  void flush();
  const t = setInterval(() => void flush(), 20_000);
  if (typeof (t as unknown as { unref?: () => void }).unref === 'function') {
    (t as unknown as { unref: () => void }).unref();
  }
  const sub = AppState.addEventListener('change', (s) => s === 'active' && void flush());
  return () => {
    outboxStarted = false;
    clearInterval(t);
    sub.remove();
  };
}
