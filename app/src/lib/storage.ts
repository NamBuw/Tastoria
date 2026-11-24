import AsyncStorage from '@react-native-async-storage/async-storage';

const USER_PREFIX = (userId: string) => `tastoria.u.${userId}.`;

/** User-scoped AsyncStorage key so offline caches and queues never bleed across accounts. */
export function getScopedKey(userId: string, name: string): string {
  return `${USER_PREFIX(userId)}${name}`;
}

const memoryPurgeHooks = new Set<(userId: string) => void>();

export function registerUserCachePurge(fn: (userId: string) => void): () => void {
  memoryPurgeHooks.add(fn);
  return () => memoryPurgeHooks.delete(fn);
}

/**
 * Purges user-scoped operational AsyncStorage entries (outbox, cook cache, meal logs) on sign-out
 * or account deletion while leaving other users' isolated storage untouched.
 */
export async function purgeUserCaches(userId: string | null | undefined): Promise<void> {
  if (!userId) return;
  memoryPurgeHooks.forEach((fn) => fn(userId));
  const prefix = USER_PREFIX(userId);
  const legacyQuickLogs = `tastoria.quick_logs.v1:${userId}`;
  try {
    const keys = await AsyncStorage.getAllKeys();
    const toRemove = keys.filter((k) => k.startsWith(prefix) || k === legacyQuickLogs);
    if (toRemove.length > 0) {
      if (typeof AsyncStorage.multiRemove === 'function') {
        await AsyncStorage.multiRemove(toRemove);
      } else {
        await Promise.all(toRemove.map((k) => AsyncStorage.removeItem(k)));
      }
    }
  } catch {
    // storage unavailable
  }
}
