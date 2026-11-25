import AsyncStorage from '@react-native-async-storage/async-storage';

import { api, ApiError } from '@/api/client';
import { analyzeMacroNutrition } from '@/components/MacroPieLedger';
import {
  applyPlateModifiers,
  type MealCalorieEstimateView,
  mergeModifiers,
  sanitizeProvenanceText,
} from '@/lib/caloriePlate';
import {
  addQuickMealLog,
  isoWeekBounds,
  listQuickMealLogs,
  removeQuickMealLog,
  syncPendingMealLogs,
} from '@/lib/mealLog';

function baseEst(overrides: Partial<MealCalorieEstimateView> = {}): MealCalorieEstimateView {
  return {
    dish_name_vi: 'Món thử',
    portion: 'vua',
    portion_multiplier: 1,
    estimated_kcal: 300,
    kcal_low: 250,
    kcal_high: 350,
    protein_g: 20,
    carbs_g: 30,
    fat_g: 10,
    fiber_g: 2,
    source: 'hybrid',
    calibrated: true,
    half_width_rel: 0.15,
    latency_ms: 5,
    nutrition_score: null,
    nutrition_grade: null,
    ...overrides,
  };
}

describe('caloriePlate edge cases', () => {
  it('ensures macro_kcal_split always sums to exactly 100%', () => {
    const est = baseEst({ protein_g: 50.5, carbs_g: 49.5, fat_g: 0 });
    const adj = applyPlateModifiers(est, []);
    expect(adj.macro_kcal_split).toEqual({ protein_pct: 51, carbs_pct: 49, fat_pct: 0 });
    const split = adj.macro_kcal_split!;
    expect(split.protein_pct + split.carbs_pct + split.fat_pct).toBe(100);
  });

  it('sets macro_kcal_split to null when modifiers clamp plate macros to 0', () => {
    const est = baseEst({
      estimated_kcal: 100,
      kcal_low: 80,
      kcal_high: 120,
      protein_g: 1,
      carbs_g: 10,
      fat_g: 4,
      macro_kcal_split: { protein_pct: 8, carbs_pct: 40, fat_pct: 52 },
    });
    const adj = applyPlateModifiers(est, ['it_com_bun', 'it_dau_mo']);
    expect(adj.estimated_kcal).toBe(0);
    expect(adj.protein_g).toBe(0);
    expect(adj.carbs_g).toBe(0);
    expect(adj.fat_g).toBe(0);
    expect(adj.macro_kcal_split).toBeNull();
  });

  it('sanitizes Nutrition-5k and YukaApp provenance variants', () => {
    const out = sanitizeProvenanceText('Tham chiếu Nutrition-5k và YukaApp');
    expect(out.toLowerCase()).not.toContain('nutrition');
    expect(out.toLowerCase()).not.toContain('5k');
    expect(out.toLowerCase()).not.toContain('yuka');
  });

  it('passes through and updates estimated_mass_g across modifiers', () => {
    const est = baseEst({ estimated_mass_g: 420 });
    const baseAdj = applyPlateModifiers(est, []);
    expect(baseAdj.estimated_mass_g).toBe(420);

    const modAdj = applyPlateModifiers(est, ['mo_hanh', 'it_com_bun']);
    expect(modAdj.estimated_mass_g).toBe(365); // 420 + 15 - 70
  });

  it('matches MacroPieLedger Hamilton macro_kcal_split 100% across fractional values', () => {
    const samples = [
      { protein_g: 13.3, carbs_g: 41.7, fat_g: 9.1 },
      { protein_g: 27.4, carbs_g: 68.2, fat_g: 26.8 },
      { protein_g: 19.5, carbs_g: 31.1, fat_g: 11.4 },
    ];
    for (const s of samples) {
      const est = baseEst(s);
      const adj = applyPlateModifiers(est, []);
      const ledger = analyzeMacroNutrition({
        proteinG: adj.protein_g,
        carbsG: adj.carbs_g,
        fatG: adj.fat_g,
      });
      expect(adj.macro_kcal_split).toEqual({
        carbs_pct: ledger.slices[0].pct,
        protein_pct: ledger.slices[1].pct,
        fat_pct: ledger.slices[2].pct,
      });
    }
  });

  it('collapses multi-whitespace when deduplicating modifiers', () => {
    const merged = mergeModifiers([
      { id: 'c1', label_vi: 'Thêm   nước tương', kcal_delta: 20, fat_delta_g: 0, carbs_delta_g: 2, protein_delta_g: 1 },
      { id: 'c2', label_vi: 'Thêm nước tương', kcal_delta: 25, fat_delta_g: 0, carbs_delta_g: 2, protein_delta_g: 1 },
    ]);
    const matching = merged.filter((m) => m.id === 'c1' || m.id === 'c2');
    expect(matching).toHaveLength(1);
  });
});

describe('mealLog week validation and concurrency', () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
  });

  it('rejects invalid ISO week 2025-W53 while accepting valid 2026-W53', () => {
    expect(isoWeekBounds('2025-W53')).toBeNull();
    expect(isoWeekBounds('2026-W53')).toEqual({ start: '2026-12-28', end: '2027-01-03' });
  });

  it('serializes concurrent addQuickMealLog calls so no entry is lost', async () => {
    const postSpy = jest.spyOn(api, 'POST').mockRejectedValue(new Error('offline'));
    const getSpy = jest.spyOn(api, 'GET').mockRejectedValue(new Error('offline'));
    const common = {
      date: '2026-11-24',
      meal_slot: 'trua' as const,
      source_kind: 'scan_calorie' as const,
      portion_label: 'Vừa 1.0×',
      modifiers_vi: [],
      kcal_low: 300,
      kcal_high: 400,
      protein_g: 20,
      carbs_g: 40,
      fat_g: 10,
      fiber_g: 2,
      provenance_label_vi: 'Viện Dinh dưỡng Quốc gia & Ảnh',
    };
    try {
      await Promise.all([
        addQuickMealLog({ ...common, title_vi: 'Phở bò', kcal: 420 }, 'u-conc'),
        addQuickMealLog({ ...common, title_vi: 'Bún chả', kcal: 480 }, 'u-conc'),
      ]);
      const list = await listQuickMealLogs('u-conc');
      expect(list).toHaveLength(2);
      expect(list.map((e) => e.title_vi).sort()).toEqual(['Bún chả', 'Phở bò']);
    } finally {
      postSpy.mockRestore();
      getSpy.mockRestore();
    }
  });
});

describe('persistent /meal-logs CRUD, offline fallback, and unbounded history', () => {
  const sampleInput = {
    date: '2026-11-24',
    meal_slot: 'trua' as const,
    title_vi: 'Cơm tấm sườn',
    source_kind: 'scan_calorie' as const,
    portion_label: 'Vừa 1.0×',
    modifiers_vi: [],
    kcal: 550,
    kcal_low: 500,
    kcal_high: 600,
    protein_g: 28,
    carbs_g: 64,
    fat_g: 18,
    fiber_g: 3,
    provenance_label_vi: 'Viện Dinh dưỡng Quốc gia & Ảnh',
  };

  beforeEach(async () => {
    await AsyncStorage.clear();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('persists, lists across cursor pages (>200 entries), and deletes via /meal-logs when online', async () => {
    const serverRow = (id: string, title = 'Cơm tấm sườn', idx = 0) => ({
      id,
      user_id: 'u-online',
      logged_at: `2026-11-24T12:${String(idx % 60).padStart(2, '0')}:00Z`,
      logged_date: '2026-11-24',
      meal_slot: 'trua' as const,
      title,
      source_type: 'scan_calorie' as const,
      source_ref_id: null,
      portion_label: 'Vừa 1.0×',
      portion_scale: 1,
      modifiers: [],
      kcal: 550,
      kcal_low: 500,
      kcal_high: 600,
      protein_g: 28,
      carbs_g: 64,
      fat_g: 18,
      fiber_g: 3,
      provenance_label_vi: 'Viện Dinh dưỡng Quốc gia & Ảnh',
      items: [],
    });

    const postSpy = jest.spyOn(api, 'POST').mockResolvedValueOnce({
      data: serverRow('srv-1'),
      response: { ok: true, status: 201 } as unknown as Response,
    } as never);

    const created = await addQuickMealLog(sampleInput, 'u-online', 'idem-online-1');
    expect(created.id).toBe('srv-1');
    expect(created.pendingSync).toBe(false);
    expect(postSpy).toHaveBeenCalledWith(
      '/meal-logs',
      expect.objectContaining({
        params: { header: { 'Idempotency-Key': 'idem-online-1' } },
      }),
    );

    const page1 = Array.from({ length: 120 }, (_, i) => serverRow(`m-${i}`, `Món ${i}`, i));
    const page2 = Array.from({ length: 110 }, (_, i) => serverRow(`m-${120 + i}`, `Món ${120 + i}`, i));
    jest
      .spyOn(api, 'GET')
      .mockResolvedValueOnce({
        data: { items: page1, next_cursor: 'cur-2' },
        response: { ok: true, status: 200 } as unknown as Response,
      } as never)
      .mockResolvedValueOnce({
        data: { items: page2, next_cursor: null },
        response: { ok: true, status: 200 } as unknown as Response,
      } as never);

    const listed = await listQuickMealLogs('u-online');
    expect(listed).toHaveLength(230); // no silent 200-entry FIFO truncation

    const delSpy = jest.spyOn(api, 'DELETE').mockResolvedValueOnce({
      data: undefined,
      response: { ok: true, status: 204 } as unknown as Response,
    } as never);
    await removeQuickMealLog('srv-1', 'u-online');
    expect(delSpy).toHaveBeenCalledWith('/meal-logs/{id}', { params: { path: { id: 'srv-1' } } });
  });

  it('queues offline on ApiError status 0 and replays via syncPendingMealLogs, but propagates non-network 422 errors', async () => {
    jest.spyOn(api, 'POST').mockResolvedValueOnce({
      error: { type: 'about:blank', title: 'Bad input', status: 422, code: 'validation_error' },
      response: { ok: false, status: 422 } as unknown as Response,
    } as never);

    await expect(addQuickMealLog(sampleInput, 'u-err')).rejects.toBeInstanceOf(ApiError);

    // Simulate network failure (status 0)
    jest.spyOn(api, 'POST').mockRejectedValueOnce(new Error('offline'));
    const offlineEntry = await addQuickMealLog(sampleInput, 'u-err', 'idem-off-1');
    expect(offlineEntry.id.startsWith('local-')).toBe(true);
    expect(offlineEntry.pendingSync).toBe(true);

    const syncedRow = {
      id: 'srv-synced-1',
      user_id: 'u-err',
      logged_at: '2026-11-24T12:00:00Z',
      logged_date: '2026-11-24',
      meal_slot: 'trua' as const,
      title: 'Cơm tấm sườn',
      source_type: 'scan_calorie' as const,
      source_ref_id: null,
      portion_label: 'Vừa 1.0×',
      portion_scale: 1,
      modifiers: [],
      kcal: 550,
      kcal_low: 500,
      kcal_high: 600,
      protein_g: 28,
      carbs_g: 64,
      fat_g: 18,
      fiber_g: 3,
      provenance_label_vi: 'Viện Dinh dưỡng Quốc gia & Ảnh',
      items: [],
    };
    const replaySpy = jest.spyOn(api, 'POST').mockResolvedValueOnce({
      data: syncedRow,
      response: { ok: true, status: 201 } as unknown as Response,
    } as never);
    replaySpy.mockClear();
    await syncPendingMealLogs('u-err');
    expect(replaySpy).toHaveBeenCalledTimes(1);

    // Offline read now reads synced cache instead of pending local entry
    jest.spyOn(api, 'GET').mockRejectedValueOnce(new Error('offline'));
    const cached = await listQuickMealLogs('u-err');
    expect(cached.map((x) => x.id)).toEqual(['srv-synced-1']);
  });
});
