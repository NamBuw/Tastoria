import AsyncStorage from '@react-native-async-storage/async-storage';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api, call, type Schemas } from '@/api/client';

type Session = Schemas['CookSession'];
const KEY = (id: string) => `tastoria.cook.${id}`;
const DONE = (id: string) => `tastoria.cook.${id}.done`;

/**
 * Cook session with its schedule; the last copy is kept on the device so the timeline keeps running
 * without a connection and after a restart (UC19 13a, 13b).
 */
export function useCookSession(id: string) {
  return useQuery({
    queryKey: ['cook', id],
    queryFn: async (): Promise<Session> => {
      try {
        const s = await call(api.GET('/cook-sessions/{id}', { params: { path: { id } } }));
        AsyncStorage.setItem(KEY(id), JSON.stringify(s)).catch(() => {});
        return s;
      } catch (e) {
        const raw = await AsyncStorage.getItem(KEY(id)).catch(() => null);
        if (raw) return JSON.parse(raw) as Session;
        throw e;
      }
    },
  });
}

/** Steps the cook ticked as done ("Xong bước"), kept on the device. */
export function useDoneSteps(id: string) {
  const [done, setDone] = useState<string[]>([]);
  useEffect(() => {
    AsyncStorage.getItem(DONE(id))
      .then((raw) => raw && setDone(JSON.parse(raw) as string[]))
      .catch(() => {});
  }, [id]);
  const mark = (key: string) => {
    setDone((cur) => {
      const next = cur.includes(key) ? cur : [...cur, key];
      AsyncStorage.setItem(DONE(id), JSON.stringify(next)).catch(() => {});
      return next;
    });
  };
  return { done, mark };
}

export const stepKey = (e: Schemas['ScheduleEntry']) => `${e.recipe_id}:${e.step_no}`;

/** Re-render every second; times are absolute (started_at + offset), so a sleeping app never drifts. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(Date.now());
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
