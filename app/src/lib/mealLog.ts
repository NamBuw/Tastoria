import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQuery } from '@tanstack/react-query';

import { api, ApiError, call, getCurrentUserId, type Schemas } from '@/api/client';
import { useSession } from '@/auth/session';
import { uuid } from './ids';
import { getScopedKey } from './storage';

export type MealSlot = 'sang' | 'trua' | 'toi' | 'phu';

export const MEAL_SLOT_LABEL: Record<MealSlot, string> = {
  sang: 'Sáng',
  trua: 'Trưa',
  toi: 'Tối',
  phu: 'Phụ',
};

export const MEAL_SLOTS: readonly MealSlot[] = ['sang', 'trua', 'toi', 'phu'];

export function defaultMealSlot(d = new Date()): MealSlot {
  const h = d.getHours();
  if (h < 10) return 'sang';
  if (h < 14) return 'trua';
  if (h < 18) return 'phu';
  return 'toi';
}

export function localDateString(d = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function isoWeekKey(dt: Date): string {
  const t = new Date(Date.UTC(dt.getUTCFullYear(), dt.getUTCMonth(), dt.getUTCDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y = t.getUTCFullYear();
  const w = Math.ceil(((t.getTime() - Date.UTC(y, 0, 1)) / 86400_000 + 1) / 7);
  return `${y}-W${String(w).padStart(2, '0')}`;
}

export function isoWeekBounds(week: string): { start: string; end: string } | null {
  const match = /^(\d{4})-W(\d{2})$/.exec(week.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const w = Number(match[2]);
  if (!Number.isFinite(year) || !Number.isFinite(w) || w < 1 || w > 53) return null;

  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Day = jan4.getUTCDay() || 7;
  const week1Monday = new Date(jan4.getTime() - (jan4Day - 1) * 86400_000);
  const start = new Date(week1Monday.getTime() + (w - 1) * 7 * 86400_000);
  if (isoWeekKey(start) !== `${year}-W${String(w).padStart(2, '0')}`) return null;
  const end = new Date(start.getTime() + 6 * 86400_000);
  const fmt = (dt: Date) => dt.toISOString().slice(0, 10);
  return { start: fmt(start), end: fmt(end) };
}

export type QuickMealLogEntry = {
  id: string;
  date: string;
  logged_at: string;
  meal_slot: MealSlot;
  title_vi: string;
  source_kind: 'scan_calorie' | 'barcode';
  portion_label: string;
  modifiers_vi: string[];
  kcal: number;
  kcal_low: number;
  kcal_high: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  provenance_label_vi: string;
  pendingSync?: boolean;
};

export type QuickMealLogInput = Omit<QuickMealLogEntry, 'id' | 'date' | 'logged_at' | 'pendingSync'> & {
  date?: string;
  logged_at?: string;
  source_ref_id?: string | null;
  portion_scale?: number;
  items?: Schemas['MealLogItemIn'][];
};

type PendingMealLog = {
  entry: QuickMealLogEntry;
  body: Schemas['MealLogCreate'];
  idempotencyKey: string;
};

const cacheKey = (userId: string) => getScopedKey(userId, 'meal_logs.v1');
const pendingKey = (userId: string) => getScopedKey(userId, 'meal_logs.pending.v1');

const writeQueues = new Map<string, Promise<unknown>>();

function enqueueWrite<T>(key: string, task: () => Promise<T>): Promise<T> {
  const prev = writeQueues.get(key) ?? Promise.resolve();
  const next = prev.catch(() => undefined).then(task);
  const tail = next.then(
    () => undefined,
    () => undefined,
  );
  writeQueues.set(key, tail);
  next.finally(() => {
    if (writeQueues.get(key) === tail) writeQueues.delete(key);
  });
  return next;
}

export function mealLogOutToEntry(m: Schemas['MealLogOut']): QuickMealLogEntry {
  return {
    id: m.id,
    date: m.logged_date,
    logged_at: m.logged_at,
    meal_slot: m.meal_slot,
    title_vi: m.title,
    source_kind: m.source_type === 'barcode' ? 'barcode' : 'scan_calorie',
    portion_label: m.portion_label,
    modifiers_vi: (m.modifiers ?? []).map((x) => String(x)),
    kcal: m.kcal,
    kcal_low: m.kcal_low,
    kcal_high: m.kcal_high,
    protein_g: m.protein_g,
    carbs_g: m.carbs_g,
    fat_g: m.fat_g,
    fiber_g: m.fiber_g,
    provenance_label_vi: m.provenance_label_vi,
    pendingSync: false,
  };
}

async function readStoredList<T>(key: string): Promise<T[]> {
  try {
    const raw = await AsyncStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

async function writeStoredList<T>(key: string, list: T[]): Promise<void> {
  try {
    await AsyncStorage.setItem(key, JSON.stringify(list));
  } catch {
    // storage unavailable
  }
}

async function readCachedEntries(userId: string): Promise<QuickMealLogEntry[]> {
  const list = await readStoredList<QuickMealLogEntry>(cacheKey(userId));
  return list.filter((item) => Boolean(item && typeof item.id === 'string' && typeof item.date === 'string'));
}

async function readPendingLogs(userId: string): Promise<PendingMealLog[]> {
  const list = await readStoredList<PendingMealLog>(pendingKey(userId));
  return list.filter((item) => Boolean(item?.entry?.id && item.body));
}

function mergeByIdDesc(entries: QuickMealLogEntry[]): QuickMealLogEntry[] {
  const seen = new Map<string, QuickMealLogEntry>();
  for (const e of entries) {
    if (!seen.has(e.id)) seen.set(e.id, e);
  }
  return [...seen.values()].sort((a, b) => (b.logged_at || '').localeCompare(a.logged_at || ''));
}

function toCreateBody(input: QuickMealLogInput): Schemas['MealLogCreate'] {
  const lo = Math.min(input.kcal_low, input.kcal);
  const hi = Math.max(input.kcal_high, input.kcal);
  return {
    meal_slot: input.meal_slot,
    title: input.title_vi,
    source_type: input.source_kind,
    source_ref_id: input.source_ref_id ?? null,
    portion_label: input.portion_label,
    portion_scale: input.portion_scale ?? 1.0,
    modifiers: input.modifiers_vi,
    kcal: input.kcal,
    kcal_low: lo,
    kcal_high: hi,
    protein_g: input.protein_g,
    carbs_g: input.carbs_g,
    fat_g: input.fat_g,
    fiber_g: input.fiber_g,
    provenance_label_vi: input.provenance_label_vi,
    ...(input.date ? { logged_date: input.date } : {}),
    ...(input.logged_at ? { logged_at: input.logged_at } : {}),
    ...(input.items?.length ? { items: input.items } : {}),
  };
}

export async function listQuickMealLogs(userId?: string | null, week?: string): Promise<QuickMealLogEntry[]> {
  const uid = userId ?? getCurrentUserId();
  if (!uid) return [];
  const bounds = week ? isoWeekBounds(week) : null;
  const filterBounds = (list: QuickMealLogEntry[]) =>
    bounds ? list.filter((e) => e.date >= bounds.start && e.date <= bounds.end) : list;

  try {
    const serverEntries: QuickMealLogEntry[] = [];
    let cursor: string | undefined;
    let page = 0;
    do {
      const res = await call(
        api.GET('/meal-logs', {
          params: {
            query: {
              ...(bounds ? { from: bounds.start, to: bounds.end } : {}),
              cursor,
              limit: 100,
            },
          },
        }),
      );
      const items = Array.isArray(res?.items) ? res.items : [];
      serverEntries.push(...items.map(mealLogOutToEntry));
      cursor = res?.next_cursor ?? undefined;
      page += 1;
    } while (cursor && page < 20);

    await enqueueWrite(cacheKey(uid), async () => {
      if (!bounds) {
        await writeStoredList(cacheKey(uid), mergeByIdDesc(serverEntries));
      } else {
        const prev = await readCachedEntries(uid);
        const outside = prev.filter((e) => e.date < bounds.start || e.date > bounds.end);
        await writeStoredList(cacheKey(uid), mergeByIdDesc([...serverEntries, ...outside]));
      }
    });

    const pending = await readPendingLogs(uid);
    return mergeByIdDesc([...filterBounds(pending.map((p) => p.entry)), ...serverEntries]);
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) {
      const [cached, pending] = await Promise.all([readCachedEntries(uid), readPendingLogs(uid)]);
      return filterBounds(mergeByIdDesc([...pending.map((p) => p.entry), ...cached]));
    }
    throw e;
  }
}

export async function addQuickMealLog(
  input: QuickMealLogInput,
  userId?: string | null,
  idempotencyKey?: string,
): Promise<QuickMealLogEntry> {
  const uid = userId ?? getCurrentUserId();
  if (!uid) throw new ApiError(401, { type: 'about:blank', title: 'Chưa đăng nhập', status: 401, code: 'unauthenticated' });

  const body = toCreateBody(input);
  const idemKey = idempotencyKey ?? uuid();

  try {
    const created = await call(
      api.POST('/meal-logs', {
        body,
        params: { header: { 'Idempotency-Key': idemKey } },
      }),
    );
    const entry = mealLogOutToEntry(created);
    await enqueueWrite(cacheKey(uid), async () => {
      const prev = await readCachedEntries(uid);
      await writeStoredList(cacheKey(uid), mergeByIdDesc([entry, ...prev]));
    });
    return entry;
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 0)) {
      throw e;
    }
    // Offline fallback: store in user-scoped pending queue without truncating history.
    const now = new Date();
    const localEntry: QuickMealLogEntry = {
      id: `local-${uuid()}`,
      date: input.date ?? localDateString(now),
      logged_at: input.logged_at ?? now.toISOString(),
      meal_slot: input.meal_slot,
      title_vi: input.title_vi,
      source_kind: input.source_kind,
      portion_label: input.portion_label,
      modifiers_vi: input.modifiers_vi,
      kcal: input.kcal,
      kcal_low: input.kcal_low,
      kcal_high: input.kcal_high,
      protein_g: input.protein_g,
      carbs_g: input.carbs_g,
      fat_g: input.fat_g,
      fiber_g: input.fiber_g,
      provenance_label_vi: input.provenance_label_vi,
      pendingSync: true,
    };
    const pendingItem: PendingMealLog = {
      entry: localEntry,
      body: {
        ...body,
        logged_date: localEntry.date,
        logged_at: localEntry.logged_at,
      },
      idempotencyKey: idemKey,
    };
    await enqueueWrite(pendingKey(uid), async () => {
      const prev = await readPendingLogs(uid);
      await writeStoredList(pendingKey(uid), [pendingItem, ...prev]);
    });
    return localEntry;
  }
}

export async function removeQuickMealLog(id: string, userId?: string | null): Promise<void> {
  const uid = userId ?? getCurrentUserId();
  if (!uid) return;

  if (!id.startsWith('local-')) {
    try {
      await call(api.DELETE('/meal-logs/{id}', { params: { path: { id } } }));
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) {
        throw e;
      }
    }
  }

  await enqueueWrite(pendingKey(uid), async () => {
    const prev = await readPendingLogs(uid);
    const next = prev.filter((item) => item.entry.id !== id);
    if (next.length !== prev.length) await writeStoredList(pendingKey(uid), next);
  });

  await enqueueWrite(cacheKey(uid), async () => {
    const prev = await readCachedEntries(uid);
    const next = prev.filter((item) => item.id !== id);
    if (next.length !== prev.length) await writeStoredList(cacheKey(uid), next);
  });
}

export async function syncPendingMealLogs(userId?: string | null): Promise<void> {
  const activeUid = getCurrentUserId();
  const uid = userId ?? activeUid;
  if (!uid || (activeUid && uid !== activeUid)) return;
  const snapshot = await readPendingLogs(uid);
  if (!snapshot.length) return;

  for (const item of snapshot) {
    const currentUid = getCurrentUserId();
    if (currentUid && currentUid !== uid) break;
    try {
      const created = await call(
        api.POST('/meal-logs', {
          body: item.body,
          params: { header: { 'Idempotency-Key': item.idempotencyKey } },
        }),
      );
      const entry = mealLogOutToEntry(created);
      await enqueueWrite(pendingKey(uid), async () => {
        const latest = await readPendingLogs(uid);
        await writeStoredList(pendingKey(uid), latest.filter((x) => x.entry.id !== item.entry.id));
      });
      await enqueueWrite(cacheKey(uid), async () => {
        const prev = await readCachedEntries(uid);
        await writeStoredList(cacheKey(uid), mergeByIdDesc([entry, ...prev]));
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) break;
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 401 && e.status !== 429) {
        await enqueueWrite(pendingKey(uid), async () => {
          const latest = await readPendingLogs(uid);
          await writeStoredList(pendingKey(uid), latest.filter((x) => x.entry.id !== item.entry.id));
        });
      }
    }
  }
}

export function useQuickMealLogs(week?: string) {
  const { user, status } = useSession();
  const userId = user?.id ?? null;
  return useQuery({
    queryKey: ['quick-logs', userId ?? 'none', week ?? 'all'],
    queryFn: async () => {
      await syncPendingMealLogs(userId).catch(() => {});
      return listQuickMealLogs(userId, week);
    },
    enabled: status === 'signedIn' && Boolean(userId),
  });
}
