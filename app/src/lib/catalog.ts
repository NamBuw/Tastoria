import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { api, call, type Schemas } from '@/api/client';
import { useSession } from '@/auth/session';

type Snapshot = Schemas['CatalogSnapshot'];
const KEY = 'tastoria.catalog.v1';

/**
 * Published catalog (recipes with steps, ingredients with food group and units) from GET /catalog/snapshot,
 * kept on the device so cooking and recipe details work without a connection (UC19 12, 13a).
 */
export function useCatalog() {
  const { status } = useSession();
  const q = useQuery({
    queryKey: ['catalog'],
    enabled: status === 'signedIn',
    staleTime: 6 * 60 * 60_000,
    gcTime: Infinity,
    queryFn: async (): Promise<Snapshot> => {
      try {
        const snap = await call(api.GET('/catalog/snapshot'));
        AsyncStorage.setItem(KEY, JSON.stringify(snap)).catch(() => {});
        return snap;
      } catch (e) {
        const raw = await AsyncStorage.getItem(KEY).catch(() => null);
        if (raw) return JSON.parse(raw) as Snapshot;
        throw e;
      }
    },
  });
  const maps = useMemo(() => {
    const ingredients = new Map<string, Schemas['Ingredient']>();
    const recipes = new Map<string, Schemas['Recipe']>();
    q.data?.ingredients.forEach((i) => ingredients.set(i.id, i));
    q.data?.recipes.forEach((r) => recipes.set(r.id, r));
    return { ingredients, recipes };
  }, [q.data]);
  return { ...q, ...maps };
}
