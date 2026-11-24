import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';
import React from 'react';

import { api } from '@/api/client';
import ExploreRecipes from '@/app/kham-pha';

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

const RECIPE_CA_KHO = {
  id: 'rec-1',
  name_vi: 'Cá thu kho tộ',
  slot: 'man',
  method_code: 'kho',
  total_minutes: 30,
  kcal_per_serving: 410,
  protein_g: 28,
  carbs_g: 12,
  fat_g: 14,
  fiber_g: 3,
  pantry_match_ratio: 1,
};

const RECIPE_RAU_XAO = {
  id: 'rec-2',
  name_vi: 'Rau muống xào tỏi',
  slot: 'rau',
  method_code: 'xao',
  total_minutes: 15,
  kcal_per_serving: 140,
  protein_g: 6,
  carbs_g: 10,
  fat_g: 7,
  fiber_g: 4,
  pantry_match_ratio: 0.5,
};

describe('kham-pha (ExploreRecipes)', () => {
  beforeEach(() => {
    setWindowWidth(1280, 900);
    mockedGet.mockReset();
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it('renders macro badges, pantry_match_ratio, and applies search and filters', async () => {
    mockedGet.mockImplementation(async (path: string, opts?: { params?: { query?: Record<string, unknown> } }) => {
      if (path === '/reference') {
        return okRes({
          cooking_methods: [
            { code: 'kho', name_vi: 'Kho' },
            { code: 'xao', name_vi: 'Xào' },
          ],
          food_groups: [],
          allergen_groups: [],
          qty_levels: [],
        });
      }
      if (path === '/catalog/snapshot') {
        return okRes({ recipes: [], ingredients: [] });
      }
      if (path === '/pantry/lots') {
        return okRes({ items: [] });
      }
      if (path === '/recipes') {
        const q = opts?.params?.query ?? {};
        const items = q.slot === 'man' ? [RECIPE_CA_KHO] : [RECIPE_CA_KHO, RECIPE_RAU_XAO];
        return okRes({ items, next_cursor: null });
      }
      return okRes({});
    });

    await renderWithProviders(<ExploreRecipes />);

    await waitFor(() => {
      expect(screen.getAllByTestId('explore-recipe-card')).toHaveLength(2);
    });

    expect(screen.getByText('Cá thu kho tộ')).toBeTruthy();
    expect(screen.getByText('Đạm 28g')).toBeTruthy();
    expect(screen.getByText('Tinh bột 12g')).toBeTruthy();
    expect(screen.getByText('Béo 14g')).toBeTruthy();
    expect(screen.getByText('Xơ 3g')).toBeTruthy();
    expect(screen.getByText('Đủ đồ')).toBeTruthy();
    expect(screen.getByText('50% đồ')).toBeTruthy();

    await fireEvent.press(screen.getByRole('checkbox', { name: 'Mặn' }));
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Tối đa 30 phút' }));
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Đủ đồ trong kho' }));
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Kho' }));

    await waitFor(() => {
      const recipeCalls = mockedGet.mock.calls.filter(([p]) => p === '/recipes');
      const lastQuery = recipeCalls[recipeCalls.length - 1]?.[1]?.params?.query;
      expect(lastQuery).toMatchObject({
        slot: 'man',
        max_minutes: 30,
        pantry_match: true,
        method_code: 'kho',
      });
    });

    jest.useFakeTimers();
    await fireEvent.changeText(screen.getByTestId('explore-search'), 'cá kho');
    await act(async () => {
      jest.advanceTimersByTime(300);
    });
    jest.useRealTimers();

    await waitFor(() => {
      const recipeCalls = mockedGet.mock.calls.filter(([p]) => p === '/recipes');
      const lastQuery = recipeCalls[recipeCalls.length - 1]?.[1]?.params?.query;
      expect(lastQuery).toMatchObject({ q: 'cá kho' });
    });
  });

  it('falls back to offline useCatalog() + useLots() when /recipes fails with network error', async () => {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/reference') {
        return okRes({ cooking_methods: [{ code: 'kho', name_vi: 'Kho' }], food_groups: [], allergen_groups: [], qty_levels: [] });
      }
      if (path === '/pantry/lots') {
        return okRes({
          items: [
            {
              id: 'lot-1',
              ingredient_id: 'ing-ca',
              ingredient_name_vi: 'Cá thu',
              available: true,
              balance_g_min: 350,
            },
          ],
        });
      }
      if (path === '/catalog/snapshot') {
        return okRes({
          ingredients: [],
          recipes: [
            {
              ...RECIPE_CA_KHO,
              status: 'published',
              ingredients: [{ ingredient_id: 'ing-ca', role: 'main', is_optional: false, grams: 250 }],
            },
            {
              ...RECIPE_RAU_XAO,
              status: 'published',
              ingredients: [{ ingredient_id: 'ing-rau', role: 'main', is_optional: false, grams: 300 }],
            },
          ],
        });
      }
      if (path === '/recipes') {
        throw new TypeError('Network request failed');
      }
      return okRes({});
    });

    await renderWithProviders(<ExploreRecipes />);

    await waitFor(() => {
      expect(screen.getByText('Đang xem từ bộ nhớ đệm ngoại tuyến.')).toBeTruthy();
    });
    expect(screen.getByText('Cá thu kho tộ')).toBeTruthy();
    expect(screen.getByText('Rau muống xào tỏi')).toBeTruthy();
    expect(screen.getByText('Đủ đồ')).toBeTruthy();
    expect(screen.getByText('0% đồ')).toBeTruthy();

    await fireEvent.press(screen.getByText('Đủ đồ trong kho'));
    await waitFor(() => {
      expect(screen.queryByText('Rau muống xào tỏi')).toBeNull();
    });
    expect(screen.getByText('Cá thu kho tộ')).toBeTruthy();
  });
});
