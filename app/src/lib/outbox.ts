import AsyncStorage from '@react-native-async-storage/async-storage';
import { AppState } from 'react-native';

import { rawRequest, type Schemas } from '@/api/client';
import { uuid } from './ids';

/**
 * Outbox for writes that must survive a lost connection (UC20 3a, UC15 14a):
 * "nấu xong" (POST /cook-sessions/{id}/complete with a fixed Idempotency-Key) and interaction events
 * (POST /events, de-duplicated by event_id). Entries are replayed with the same key / ids until the
 * server answers with a final status.
 */
type Entry = {
  id: string;
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
  | { state: 'pending' }
  | { state: 'done'; result: Schemas['CookCompletion'] }
  | { state: 'failed'; status: number; problem: unknown };

const KEY = 'tastoria.outbox.v1';
const RESULT = (sessionId: string) => `tastoria.complete.${sessionId}`;

let flushing: Promise<void> | null = null;
const listeners = new Set<() => void>();

async function read(): Promise<Entry[]> {
  try {
    return JSON.parse((await AsyncStorage.getItem(KEY)) ?? '[]') as Entry[];
  } catch {
    return [];
  }
}

async function write(entries: Entry[]): Promise<void> {
  try {
    await AsyncStorage.setItem(KEY, JSON.stringify(entries));
  } catch {
    // storage unavailable: entries stay in memory for this run only
  }
}

export function onOutboxChange(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  listeners.forEach((fn) => fn());
}

export async function pendingCount(): Promise<number> {
  return (await read()).length;
}

/** Queue "nấu xong" once per session; a second tap reuses the queued entry and its key. */
export async function enqueueComplete(sessionId: string, body: Schemas['CookCompleteRequest']): Promise<void> {
  const entries = await read();
  if (!entries.some((e) => e.kind === 'complete' && e.sessionId === sessionId)) {
    entries.push({
      id: uuid(),
      kind: 'complete',
      method: 'POST',
      path: `/cook-sessions/${sessionId}/complete`,
      body,
      idempotencyKey: uuid(),
      sessionId,
      createdAt: new Date().toISOString(),
      attempts: 0,
    });
    await write(entries);
    await AsyncStorage.setItem(RESULT(sessionId), JSON.stringify({ state: 'pending' })).catch(() => {});
  }
  await flush();
}

export async function getCompleteOutcome(sessionId: string): Promise<CompleteOutcome | null> {
  try {
    const raw = await AsyncStorage.getItem(RESULT(sessionId));
    return raw ? (JSON.parse(raw) as CompleteOutcome) : null;
  } catch {
    return null;
  }
}

export async function enqueueEvents(events: Omit<Schemas['InteractionEvent'], 'event_id' | 'occurred_at'>[]) {
  if (!events.length) return;
  const now = new Date().toISOString();
  const entries = await read();
  entries.push({
    id: uuid(),
    kind: 'events',
    method: 'POST',
    path: '/events',
    body: { events: events.map((e) => ({ ...e, event_id: uuid(), occurred_at: now })) },
    createdAt: now,
    attempts: 0,
  });
  await write(entries);
  void flush();
}

function retryable(status: number, problem: unknown): boolean {
  if (status === 0 || status >= 500 || status === 429 || status === 401) return true;
  const code = (problem as { code?: string } | null)?.code;
  return status === 409 && code === 'idempotency_in_progress';
}

export function flush(): Promise<void> {
  if (flushing) return flushing;
  flushing = (async () => {
    let entries = await read();
    for (const e of [...entries]) {
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
      if (status !== 0 && !retryable(status, json)) {
        entries = entries.filter((x) => x.id !== e.id);
        if (e.kind === 'complete' && e.sessionId) {
          const outcome: CompleteOutcome =
            status >= 200 && status < 300
              ? { state: 'done', result: json as Schemas['CookCompletion'] }
              : { state: 'failed', status, problem: json };
          await AsyncStorage.setItem(RESULT(e.sessionId), JSON.stringify(outcome)).catch(() => {});
        }
      } else {
        entries = entries.map((x) => (x.id === e.id ? { ...x, attempts: x.attempts + 1 } : x));
        if (status === 0) break; // offline: keep order, try again later
      }
    }
    await write(entries);
    notify();
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}

/** Retry every 20 s and whenever the app comes back to the foreground. */
export function startOutbox(): () => void {
  void flush();
  const t = setInterval(() => void flush(), 20_000);
  const sub = AppState.addEventListener('change', (s) => s === 'active' && void flush());
  return () => {
    clearInterval(t);
    sub.remove();
  };
}
