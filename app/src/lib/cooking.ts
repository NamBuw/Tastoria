import AsyncStorage from '@react-native-async-storage/async-storage';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api, ApiError, call, type Schemas } from '@/api/client';
import { useSession } from '@/auth/session';
import { getScopedKey } from './storage';

type Session = Schemas['CookSession'];
const KEY = (userId: string, id: string) => getScopedKey(userId, `cook.${id}`);
const DONE = (userId: string, id: string) => getScopedKey(userId, `cook.${id}.done`);

/**
 * Cook session with its schedule; the last copy is kept on the device (scoped by userId) so the timeline
 * keeps running on network loss (ApiError.status === 0) and after a restart (UC19 13a, 13b).
 */
export function useCookSession(id: string) {
  const { user, status } = useSession();
  const userId = user?.id;
  return useQuery({
    queryKey: ['cook', id, userId ?? 'none'],
    enabled: status === 'signedIn' && Boolean(userId && id),
    queryFn: async (): Promise<Session> => {
      try {
        const s = await call(api.GET('/cook-sessions/{id}', { params: { path: { id } } }));
        if (userId) AsyncStorage.setItem(KEY(userId, id), JSON.stringify(s)).catch(() => {});
        return s;
      } catch (e) {
        if (e instanceof ApiError && e.status === 0 && userId) {
          const raw = await AsyncStorage.getItem(KEY(userId, id)).catch(() => null);
          if (raw) return JSON.parse(raw) as Session;
        }
        throw e;
      }
    },
  });
}

/** Steps the cook ticked as done ("Xong bước"), kept per user on the device. */
export function useDoneSteps(id: string) {
  const { user } = useSession();
  const userId = user?.id;
  const scopeKey = `${userId ?? 'anon'}:${id}`;
  const [doneState, setDoneState] = useState<{ scopeKey: string; steps: string[] }>({ scopeKey, steps: [] });
  const done = doneState.scopeKey === scopeKey ? doneState.steps : [];

  useEffect(() => {
    if (!userId) return;
    let alive = true;
    AsyncStorage.getItem(DONE(userId, id))
      .then((raw) => {
        if (alive && raw) setDoneState({ scopeKey, steps: JSON.parse(raw) as string[] });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [userId, id, scopeKey]);

  const mark = (key: string) => {
    setDoneState((cur) => {
      const base = cur.scopeKey === scopeKey ? cur.steps : [];
      const next = base.includes(key) ? base : [...base, key];
      if (userId) AsyncStorage.setItem(DONE(userId, id), JSON.stringify(next)).catch(() => {});
      return { scopeKey, steps: next };
    });
  };
  return { done, mark };
}

export const stepKey = (e: Schemas['ScheduleEntry']) => `${e.recipe_id}:${e.step_no}`;

/** Re-render every second; times are absolute (started_at + offset), so a sleeping app never drifts. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function fmtClock(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function fmtLeft(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

/**
 * Keep the screen on while cooking. Same as expo-keep-awake's hook, but release waits for the activation and
 * failures (web without Wake Lock support, page hidden) are ignored instead of surfacing as errors.
 */
export function useScreenOn(tag: string) {
  useEffect(() => {
    const on = activateKeepAwakeAsync(tag).catch(() => {});
    return () => {
      void on.then(() => deactivateKeepAwake(tag)).catch(() => {});
    };
  }, [tag]);
}
