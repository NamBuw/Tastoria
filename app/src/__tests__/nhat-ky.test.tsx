import AsyncStorage from '@react-native-async-storage/async-storage';
import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import React from 'react';

import { api } from '@/api/client';
import Journal from '@/app/(tabs)/nhat-ky';
import { addQuickMealLog, listQuickMealLogs, localDateString } from '@/lib/mealLog';

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

describe('nhat-ky (Journal with Quick-Logs & Today Summary)', () => {
  beforeEach(async () => {
    setWindowWidth(1280, 900);
    mockedGet.mockReset();
    await AsyncStorage.clear();
  });

  it('merges quick-logged meals into Today summary and deletes an entry cleanly', async () => {
    const today = localDateString();
    const entry = await addQuickMealLog(
      {
        date: today,
        meal_slot: 'trua',
        title_vi: 'Phở bò tái chín',
        source_kind: 'scan_calorie',
        portion_label: 'Vừa 1.0×',
        modifiers_vi: ['Thêm mỡ hành (+80 kcal)'],
        kcal: 510,
        kcal_low: 450,
        kcal_high: 570,
        protein_g: 28,
        carbs_g: 62,
        fat_g: 15,
        fiber_g: 3,
        provenance_label_vi: 'Viện Dinh dưỡng VN & Ảnh',
      },
      'user-1',
    );

    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/me/profile') return okRes({ kcal_target: 2000 });
      if (path === '/journal') {
        return okRes({
          week: '2026-W48',
          timezone: 'Asia/Ho_Chi_Minh',
          kcal_range_status: 'calibrated',
          days: [
            {
              date: today,
              cooked_trays: 0,
              kcal_per_person: null,
              e_target_kcal: 2000,
              urgent_lots_used: 0,
            },
          ],
          macros: { protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 },
          cooked_history: [],
        });
      }
      return okRes({});
    });

    await renderWithProviders(<Journal />);

    expect(await screen.findByTestId('journal-today-summary')).toBeTruthy();
    expect(screen.getByTestId('macro-pie-chart')).toBeTruthy();
    expect(screen.getAllByText('510 kcal').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Còn lại 1490 kcal/)).toBeTruthy();

    expect(screen.getByTestId('journal-quick-logs')).toBeTruthy();
    expect(screen.getByText('Phở bò tái chín')).toBeTruthy();
    expect(screen.getByText(/Bữa Trưa/)).toBeTruthy();

    await fireEvent.press(screen.getByTestId(`quick-log-delete-${entry.id}`));
    await waitFor(async () => {
      expect(await listQuickMealLogs('user-1')).toHaveLength(0);
    });
  });

  it('hides contradictory 0 g macro tiles when today kcal comes only from cooked trays', async () => {
    const today = localDateString();
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/me/profile') return okRes({ kcal_target: 2000 });
      if (path === '/journal') {
        return okRes({
          week: '2026-W48',
          timezone: 'Asia/Ho_Chi_Minh',
          kcal_range_status: 'calibrated',
          days: [
            {
              date: today,
              cooked_trays: 1,
              kcal_per_person: 590,
              e_target_kcal: 2000,
              urgent_lots_used: 1,
            },
          ],
          macros: { protein_g: 25, carbs_g: 60, fat_g: 18, fiber_g: 6 },
          cooked_history: [],
        });
      }
      return okRes({});
    });

    await renderWithProviders(<Journal />);

    expect(await screen.findByTestId('journal-today-summary')).toBeTruthy();
    expect(screen.getAllByText('590 kcal').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId('journal-today-macro-note')).toBeTruthy();
    expect(screen.queryByText('0 g')).toBeNull();
  });

  it('computes weekly macro % via 4/4/9 energy weights (fiber separate) and avoids double-counting server meal_logs', async () => {
    const today = localDateString();
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/me/profile') return okRes({ kcal_target: 2000 });
      if (path === '/meal-logs') {
        return okRes({
          items: [
            {
              id: 'srv-ml-1',
              user_id: 'user-1',
              logged_at: `${today}T12:00:00Z`,
              logged_date: today,
              meal_slot: 'trua',
              title: 'Cơm sườn',
              source_type: 'scan_calorie',
              source_ref_id: null,
              portion_label: 'Vừa 1.0×',
              portion_scale: 1,
              modifiers: [],
              kcal: 500,
              kcal_low: 450,
              kcal_high: 550,
              protein_g: 25,
              carbs_g: 50,
              fat_g: 22,
              fiber_g: 10,
              provenance_label_vi: 'Viện Dinh dưỡng Quốc gia & Ảnh',
              items: [],
            },
          ],
          next_cursor: null,
        });
      }
      if (path === '/journal') {
        // Server journal already includes srv-ml-1 in today's kcal_per_person & weekly macros!
        // Protein 25g (100 kcal), Carbs 50g (200 kcal), Fat 22g (198 kcal) -> total 498 kcal => 20% / 40% / 40%
        return okRes({
          week: '2026-W48',
          timezone: 'Asia/Ho_Chi_Minh',
          kcal_range_status: 'calibrated',
          days: [
            {
              date: today,
              cooked_trays: 0,
              kcal_per_person: 500,
              protein_g: 25,
              carbs_g: 50,
              fat_g: 22,
              fiber_g: 10,
              e_target_kcal: 2000,
              urgent_lots_used: 0,
            },
          ],
          macros: { protein_g: 25, carbs_g: 50, fat_g: 22, fiber_g: 10 },
          meal_logs: [{ id: 'srv-ml-1' }],
          cooked_history: [],
        });
      }
      return okRes({});
    });

    await renderWithProviders(<Journal />);

    expect(await screen.findByTestId('journal-today-summary')).toBeTruthy();
    // 500 kcal (NOT double-counted 1000 kcal!)
    expect(screen.getAllByText('500 kcal').length).toBeGreaterThanOrEqual(1);
    // 4/4/9 energy split (fiber 10g NOT in percentage denominator): Đạm 20%, Tinh bột 40%, Chất béo 40%
    expect(screen.getAllByText(/Tinh bột/).length).toBeGreaterThanOrEqual(1);
    const weeklyMacroTexts = screen.getAllByTestId('macro-value').map((n) =>
      Array.isArray(n.props.children) ? n.props.children.join('') : String(n.props.children),
    );
    expect(weeklyMacroTexts).toEqual(['25 g (20%)', '50 g (40%)', '22 g (40%)']);
    expect(screen.getByText('Chất xơ (tính riêng)')).toBeTruthy();
    expect(screen.getByTestId('macro-fiber-value')).toHaveTextContent('10 g');
  });
});
