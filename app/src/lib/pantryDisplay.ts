import type { Schemas } from '@/api/client';

export type Lot = Schemas['PantryLot'];
export type Ingredient = Schemas['Ingredient'];

export const UNIT_LABEL: Record<string, string> = {
  qua: 'quả',
  bo: 'bó',
  cu: 'củ',
  nhanh: 'nhánh',
  mieng: 'miếng',
  goi: 'gói',
  hop: 'hộp',
  cay: 'cây',
  tep: 'tép',
  con: 'con',
};

const FRESH_URGENCY_RANK: Record<string, number> = {
  kiem_tra: 4,
  dung_ngay: 3,
  dung_som: 2,
  tuoi: 1,
  chua_ro: 0,
};

export type GroupedPantryItem = {
  id: string;
  ingredient_id: string;
  ingredient_name_vi: string;
  balance_g_min: number;
  balance_g_max: number;
  freshness_label: Lot['freshness_label'];
  acquired_at: string;
  acquired_basis: Lot['acquired_basis'];
  status: Lot['status'];
  available: boolean;
  hasNotSeen: boolean;
  allNotSeen: boolean;
  lots: Lot[];
  primaryLot: Lot;
};

/** Format pantry amount in natural Vietnamese kitchen units without confusing "0 đến X g" ranges. */
export function formatFriendlyQty(
  minG: number,
  maxG: number,
  ingredient?: Pick<Ingredient, 'countable' | 'units'> | null,
): string {
  const lo = Math.max(0, Number.isFinite(minG) ? minG : 0);
  const hi = Math.max(lo, Number.isFinite(maxG) ? maxG : lo);
  const mid = (lo + hi) / 2;
  const roundTen = (x: number) => (x >= 100 ? Math.round(x / 10) * 10 : Math.round(x));

  const primaryUnit = ingredient?.units?.[0];
  if (primaryUnit && primaryUnit.grams_per_unit > 0 && mid > 0) {
    const unitName = UNIT_LABEL[primaryUnit.unit_code] ?? primaryUnit.unit_code;
    const estCount = mid / primaryUnit.grams_per_unit;
    if (estCount >= 0.6) {
      const cnt = Math.max(1, Math.round(estCount));
      const approxG = roundTen(mid);
      const exactPrefix = lo === hi && Math.abs(mid - cnt * primaryUnit.grams_per_unit) <= 1 ? '' : '~';
      if (approxG >= 100) {
        return `${exactPrefix}${cnt} ${unitName} (~${approxG} g)`;
      }
      return `${exactPrefix}${cnt} ${unitName}`;
    }
    if (lo <= 0) return 'Còn ít';
  }

  const a = roundTen(lo);
  const b = roundTen(hi);
  if (a <= 0 && b <= 0) return 'Sắp hết';
  if (a <= 0) {
    if (b <= 150) return 'Còn ít';
    if (b <= 350) return 'Còn vừa';
    return 'Còn nhiều';
  }
  if (a === b) return `${a} g`;
  return `~${roundTen((lo + hi) / 2)} g`;
}

/** Merge duplicate pantry lots sharing the same ingredient into a single clear fridge card. */
export function groupLotsByIngredient(lots: Lot[]): GroupedPantryItem[] {
  const byIng = new Map<string, Lot[]>();
  for (const lot of lots) {
    const bucket = byIng.get(lot.ingredient_id);
    if (bucket) bucket.push(lot);
    else byIng.set(lot.ingredient_id, [lot]);
  }

  const groups: GroupedPantryItem[] = [];
  for (const [ingredientId, rawList] of byIng.entries()) {
    const sorted = [...rawList].sort((x, y) => {
      const rx = FRESH_URGENCY_RANK[x.freshness_label] ?? 0;
      const ry = FRESH_URGENCY_RANK[y.freshness_label] ?? 0;
      if (ry !== rx) return ry - rx;
      return x.acquired_at.localeCompare(y.acquired_at);
    });
    const primary = sorted[0];
    let worstFresh = primary.freshness_label;
    let worstRank = FRESH_URGENCY_RANK[worstFresh] ?? 0;
    let sumMin = 0;
    let sumMax = 0;
    let earliestAt = primary.acquired_at;
    let earliestBasis = primary.acquired_basis;
    for (const l of sorted) {
      const rank = FRESH_URGENCY_RANK[l.freshness_label] ?? 0;
      if (rank > worstRank) {
        worstRank = rank;
        worstFresh = l.freshness_label;
      }
      sumMin += l.balance_g_min;
      sumMax += l.balance_g_max;
      if (l.acquired_at < earliestAt) {
        earliestAt = l.acquired_at;
        earliestBasis = l.acquired_basis;
      }
    }
    const hasNotSeen = sorted.some((l) => l.status === 'not_seen');
    const allNotSeen = sorted.every((l) => l.status === 'not_seen');
    groups.push({
      id: primary.id,
      ingredient_id: ingredientId,
      ingredient_name_vi: primary.ingredient_name_vi,
      balance_g_min: sumMin,
      balance_g_max: sumMax,
      freshness_label: worstFresh,
      acquired_at: earliestAt,
      acquired_basis: earliestBasis,
      status: allNotSeen ? 'not_seen' : primary.status,
      available: sorted.some((l) => l.available),
      hasNotSeen,
      allNotSeen,
      lots: sorted,
      primaryLot: primary,
    });
  }
  return groups;
}
