import { screen } from '@testing-library/react-native';
import React from 'react';

import { api } from '@/api/client';
import RecipeDetail from '@/app/mon/[id]';
import { FOOD_PHOTOS, recipePhotoFor } from '@/components/Brand';
import { analyzeMacroNutrition, MacroPieLedger } from '@/components/MacroPieLedger';

import { mockNavState } from '../../jest.setup';
import { okRes, renderWithProviders, setWindowWidth } from './test-utils';

jest.mock('@/api/client', () => {
  const actual = jest.requireActual('@/api/client');
  return {
    ...actual,
    api: {
      GET: jest.fn(),
      POST: jest.fn(),
      PATCH: jest.fn(),
      DELETE: jest.fn(),
    },
  };
});

const mockedGet = api.GET as jest.Mock;

describe('analyzeMacroNutrition & MacroPieLedger', () => {
  it('computes macro energy, 100%-exact percentage shares, density tag, AMDR balance & fiber %', () => {
    const res = analyzeMacroNutrition({
      proteinG: 25,
      carbsG: 65,
      fatG: 14,
      fiberG: 5,
      totalKcal: 486,
      massG: 360,
      sodiumMg: 420,
      sugarG: 4,
      context: 'meal',
    });

    // 25*4=100, 65*4=260, 14*9=126 -> total=486
    expect(res.macroEnergyKcal).toBe(486);
    expect(res.slices.map((s) => s.kcal)).toEqual([260, 100, 126]);
    const pctSum = res.slices.reduce((a, s) => a + s.pct, 0);
    expect(pctSum).toBe(100);
    expect(res.amdrBalanced).toBe(true); // Carb ~53%, Protein ~21%, Lipid ~26%
    expect(res.densityKcalPer100g).toBe(135);
    expect(res.densityTagVi).toBe('Vừa năng lượng');
    expect(res.fiberDailyPct).toBe(20); // 5 / 25 = 20%
    expect(res.warningsVi).toHaveLength(0);

    // Verify all 3 unified density bands: <120, 120..200, >200
    expect(analyzeMacroNutrition({ proteinG: 5, carbsG: 15, fatG: 2, totalKcal: 98, massG: 100 }).densityTagVi).toBe('Nhẹ bụng');
    expect(analyzeMacroNutrition({ proteinG: 10, carbsG: 20, fatG: 0, totalKcal: 120, massG: 100 }).densityTagVi).toBe('Vừa năng lượng');
    expect(analyzeMacroNutrition({ proteinG: 20, carbsG: 30, fatG: 0, totalKcal: 200, massG: 100 }).densityTagVi).toBe('Vừa năng lượng');
    expect(analyzeMacroNutrition({ proteinG: 20, carbsG: 30, fatG: 1, totalKcal: 209, massG: 100 }).densityTagVi).toBe('Đậm năng lượng');
  });

  it('flags high lipid, low fiber, high sodium, and missing massG honestly', () => {
    const res = analyzeMacroNutrition({
      proteinG: 10,
      carbsG: 20,
      fatG: 22,
      fiberG: 1,
      totalKcal: 318,
      massG: null,
      sodiumMg: 920,
      sugarG: 18,
      context: 'meal',
    });

    expect(res.amdrBalanced).toBe(false);
    expect(res.densityKcalPer100g).toBeNull();
    expect(res.insightVi).toContain('Chất béo vượt mức 30%');
    expect(res.warningsVi.some((w) => w.includes('Natri cao'))).toBe(true);
    expect(res.warningsVi.some((w) => w.includes('Đường đơn cao'))).toBe(true);
    expect(res.warningsVi.some((w) => w.includes('Chất xơ còn ít'))).toBe(true);
  });

  it('renders Pure-SVG macro-pie-chart and Nutrition Facts ledger', async () => {
    await renderWithProviders(
      <MacroPieLedger
        proteinG={25}
        carbsG={65}
        fatG={14}
        fiberG={5}
        totalKcal={486}
        massG={360}
      />,
    );

    expect(screen.getByTestId('macro-pie-chart')).toBeTruthy();
    expect(screen.getByTestId('macro-donut-outer-ring')).toBeTruthy();
    expect(screen.getByTestId('macro-donut-inner-ring')).toBeTruthy();
    expect(screen.getByTestId('macro-nutrition-ledger')).toBeTruthy();
    expect(screen.getByText(/135 kcal\/100g/)).toBeTruthy();
    expect(screen.getByText(/5 g \(20% \/ 25g ngày\)/)).toBeTruthy();
    expect(screen.getByText('1g đạm, tinh bột ≈ 4 kcal, 1g béo ≈ 9 kcal')).toBeTruthy();
    expect(screen.getAllByText(/Viện Dinh dưỡng Quốc gia/).length).toBeGreaterThanOrEqual(1);
  });

  it('handles sub-calorie 0.1g inputs coherently and guards NaN/Infinity inputs', async () => {
    const sub = analyzeMacroNutrition({
      proteinG: 0.1,
      carbsG: 0.1,
      fatG: 0,
      fiberG: 0,
    });
    expect(sub.slices.map((s) => s.pct)).toEqual([50, 50, 0]);
    expect(sub.insightVi).not.toContain('Chưa có dữ liệu đa lượng');

    const bad = analyzeMacroNutrition({
      proteinG: Number.NaN,
      carbsG: Number.POSITIVE_INFINITY,
      fatG: -5,
      fiberG: Number.NaN,
      totalKcal: Number.NaN,
      massG: Number.POSITIVE_INFINITY,
    });
    expect(bad.displayKcal).toBe(0);
    expect(bad.fiberG).toBe(0);
    expect(bad.densityKcalPer100g).toBeNull();
    expect(bad.slices.map((s) => s.pct)).toEqual([0, 0, 0]);

    await renderWithProviders(<MacroPieLedger proteinG={0.1} carbsG={0.1} fatG={0} />);
    expect(screen.getByTestId('macro-pie-chart')).toBeTruthy();
  });
});

describe('Brand recipePhotoFor Vietnamese matching & slot fallback', () => {
  it('matches Cá nục kho thơm, avoids cà/cá false positives, and falls back for trang_mieng', () => {
    expect(recipePhotoFor('Cá nục kho thơm', 'man')).toBe(FOOD_PHOTOS.caramelTrout);
    expect(recipePhotoFor('Canh chua cá lóc', 'canh')).toBe(FOOD_PHOTOS.freshBowl);
    expect(recipePhotoFor('Món đặc biệt mới', 'rau')).toBeTruthy();
    expect(recipePhotoFor('Cà ri gà', 'man')).toBe(FOOD_PHOTOS.caramelPork);
    expect(recipePhotoFor('Cà tím nướng mỡ hành', 'rau')).toBe(FOOD_PHOTOS.morningGlory);
    expect(recipePhotoFor('', 'trang_mieng')).toBeTruthy();
  });
});

describe('mon/[id] (RecipeDetail editorial cleanup)', () => {
  beforeEach(() => {
    setWindowWidth(1280, 900);
    mockNavState.params = { id: 'rec-ca-nuc' };
    mockedGet.mockReset();
  });

  it('renders single MacroPieLedger without duplicate macro block or unvalidated internal source text', async () => {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/me/consents') return okRes({ items: [] });
      if (path === '/reference') {
        return okRes({
          cooking_methods: [{ code: 'kho', name_vi: 'Kho' }],
          nutrients: [{ code: 'sodium_mg', name_vi: 'Natri', unit: 'mg' }],
          food_groups: [],
          allergen_groups: [],
          qty_levels: [],
        });
      }
      if (path === '/catalog/snapshot') return okRes({ recipes: [], ingredients: [] });
      if (path === '/pantry/lots') return okRes({ items: [] });
      if (path === '/recipes/{id}') {
        return okRes({
          id: 'rec-ca-nuc',
          name_vi: 'Cá nục kho thơm',
          slot: 'man',
          method_code: 'kho',
          servings: 2,
          total_minutes: 35,
          kcal_per_serving: 360,
          protein_g: 26,
          carbs_g: 22,
          fat_g: 16,
          fiber_g: 3,
          make_ahead: null,
          nutrition_data_version: 'nin-2026',
          ingredients: [
            { ingredient_id: 'i1', name_vi: 'Cá nục', grams: 400, is_optional: false, is_staple: false },
            { ingredient_id: 'i2', name_vi: 'Thơm', grams: 160, is_optional: false, is_staple: false },
          ],
          steps: [{ step_no: 1, text_vi: 'Kho cá lửa nhỏ', minutes: 30, kind: 'active', uses_burner: true }],
          nutrition: [
            { nutrient_code: 'protein_g', per_serving: 26 },
            { nutrient_code: 'glucid_g', per_serving: 22 },
            { nutrient_code: 'lipid_g', per_serving: 16 },
            { nutrient_code: 'fiber_g', per_serving: 3 },
            { nutrient_code: 'sodium_mg', per_serving: 780 },
          ],
          sources: [
            { title: 'Tài liệu nội bộ (liên kết lỗi không bấm)', url: 'not-a-valid-url' },
            { title: 'Viện Dinh dưỡng Quốc gia', url: 'https://viendinhduong.vn/mon-ca-kho' },
          ],
        });
      }
      return okRes({});
    });

    await renderWithProviders(<RecipeDetail />);

    expect(await screen.findByTestId('screen-recipe')).toBeTruthy();
    expect(screen.getByText('Cá nục kho thơm')).toBeTruthy();
    expect(screen.getByTestId('macro-pie-chart')).toBeTruthy();
    expect(screen.getByText('Phân tích dinh dưỡng mỗi người')).toBeTruthy();
    expect(screen.queryByText('Thành phần dinh dưỡng / người')).toBeNull();
    expect(screen.queryByText('Chi tiết dinh dưỡng mỗi người')).toBeNull();
    expect(screen.queryByText(/Tài liệu nội bộ/)).toBeNull();
    expect(screen.getByText('Viện Dinh dưỡng Quốc gia')).toBeTruthy();
    expect(screen.getByLabelText('Ảnh món Cá nục kho thơm')).toBeTruthy();
  });
});
