import { formatFriendlyQty, groupLotsByIngredient, type Lot } from '@/lib/pantryDisplay';

function makeLot(overrides: Partial<Lot> = {}): Lot {
  return {
    id: 'lot-1',
    ingredient_id: 'ing-1',
    ingredient_name_vi: 'Cải ngọt',
    status: 'in_stock',
    available: true,
    freshness_label: 'tuoi',
    acquired_at: '2026-11-24T10:00:00Z',
    acquired_basis: 'purchase_date_entered',
    initial_g_min: 250,
    initial_g_max: 500,
    balance_g_min: 250,
    balance_g_max: 500,
    ...overrides,
  } as Lot;
}

describe('pantryDisplay (friendly quantities & grouped fridge items)', () => {
  it('never formats awkward "0 đến X g" ranges and converts countable items to natural units', () => {
    const eggs = {
      countable: true,
      units: [{ unit_code: 'qua' as const, grams_per_unit: 55, source: 'NIN' }],
    };
    expect(formatFriendlyQty(165, 165, eggs)).toBe('3 quả (~170 g)');
    expect(formatFriendlyQty(150, 180, eggs)).toBe('~3 quả (~170 g)');
    expect(formatFriendlyQty(55, 55, eggs)).toBe('1 quả');

    const greens = {
      countable: false,
      units: [{ unit_code: 'bo' as const, grams_per_unit: 300, source: 'NIN' }],
    };
    expect(formatFriendlyQty(250, 350, greens)).toBe('~1 bó (~300 g)');

    // Ranges starting at 0 map to human levels instead of "0 đến 300 g"
    expect(formatFriendlyQty(0, 120, null)).toBe('Còn ít');
    expect(formatFriendlyQty(0, 300, null)).toBe('Còn vừa');
    expect(formatFriendlyQty(0, 600, null)).toBe('Còn nhiều');
    expect(formatFriendlyQty(0, 0, null)).toBe('Sắp hết');
    expect(formatFriendlyQty(250, 500, null)).toBe('~380 g');
    expect(formatFriendlyQty(500, 500, null)).toBe('500 g');
    expect(formatFriendlyQty(0, 300, null)).not.toContain('0 đến');
  });

  it('merges duplicate lots by ingredient_id and elevates worst urgency freshness', () => {
    const grouped = groupLotsByIngredient([
      makeLot({
        id: 'l-fresh',
        ingredient_id: 'ing-nam',
        ingredient_name_vi: 'Nấm rơm',
        freshness_label: 'tuoi',
        acquired_at: '2026-11-25T08:00:00Z',
        balance_g_min: 100,
        balance_g_max: 200,
      }),
      makeLot({
        id: 'l-urgent',
        ingredient_id: 'ing-nam',
        ingredient_name_vi: 'Nấm rơm',
        freshness_label: 'dung_ngay',
        acquired_at: '2026-11-22T08:00:00Z',
        balance_g_min: 50,
        balance_g_max: 100,
        status: 'not_seen',
      }),
      makeLot({
        id: 'l-egg',
        ingredient_id: 'ing-trung',
        ingredient_name_vi: 'Trứng gà',
        freshness_label: 'tuoi',
        balance_g_min: 165,
        balance_g_max: 165,
      }),
    ]);

    expect(grouped).toHaveLength(2);
    const nam = grouped.find((g) => g.ingredient_id === 'ing-nam')!;
    expect(nam.lots).toHaveLength(2);
    expect(nam.balance_g_min).toBe(150);
    expect(nam.balance_g_max).toBe(300);
    expect(nam.freshness_label).toBe('dung_ngay');
    expect(nam.hasNotSeen).toBe(true);
    expect(nam.allNotSeen).toBe(false);
    expect(nam.primaryLot.id).toBe('l-urgent');
  });
});
