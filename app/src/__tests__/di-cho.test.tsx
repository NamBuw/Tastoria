import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import React from 'react';

import { api } from '@/api/client';
import Shopping from '@/app/(tabs)/di-cho';

import { errRes, okRes, renderWithProviders, setWindowWidth } from './test-utils';

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
const mockedPost = api.POST as jest.Mock;

describe('di-cho (Shopping)', () => {
  beforeEach(() => {
    setWindowWidth(1280, 900);
    mockedGet.mockReset();
    mockedPost.mockReset();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('posts directly to /shopping-items/{id}/to-pantry when qty_g != null', async () => {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/shopping-items') {
        return okRes({
          items: [
            {
              id: 'shop-1',
              ingredient_id: 'ing-thit',
              ingredient_name_vi: 'Thịt lợn',
              qty_g: 300,
              status: 'open',
              note: null,
              source_meal_plan_item_id: null,
            },
          ],
        });
      }
      if (path === '/catalog/snapshot') return okRes({ ingredients: [], recipes: [] });
      if (path === '/reference') return okRes({ qty_levels: [], cooking_methods: [], food_groups: [], allergen_groups: [] });
      return okRes({});
    });
    mockedPost.mockResolvedValueOnce(okRes({ lot: { id: 'lot-1' } }));

    await renderWithProviders(<Shopping />);

    const btn = await screen.findByTestId('shop-to-pantry-Thịt lợn');
    await fireEvent.press(btn);

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith('/shopping-items/{id}/to-pantry', {
        params: { path: { id: 'shop-1' } },
        body: {},
      });
    });
    expect(await screen.findByText('Đã thêm Thịt lợn vào Kho bếp')).toBeTruthy();
  });

  it('opens AddLotSheet fallback when qty_g == null and submits resolved qty_g', async () => {
    const tomatoIng = {
      id: 'ing-cachua',
      name_vi: 'Cà chua',
      food_group_code: 'rau_cu',
      is_staple: false,
      countable: true,
      shelf_life_days: 7,
      allergen_codes: [],
      units: [],
      synonyms: [],
    };
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/shopping-items') {
        return okRes({
          items: [
            {
              id: 'shop-2',
              ingredient_id: 'ing-cachua',
              ingredient_name_vi: 'Cà chua',
              qty_g: null,
              status: 'open',
              note: null,
              source_meal_plan_item_id: null,
            },
          ],
        });
      }
      if (path === '/catalog/snapshot') return okRes({ ingredients: [tomatoIng], recipes: [] });
      if (path === '/reference') return okRes({ qty_levels: [], cooking_methods: [], food_groups: [], allergen_groups: [] });
      return okRes({});
    });
    mockedPost.mockResolvedValueOnce(okRes({ lot: { id: 'lot-2' } }));

    await renderWithProviders(<Shopping />);

    const btn = await screen.findByTestId('shop-to-pantry-Cà chua');
    await fireEvent.press(btn);

    expect(mockedPost).not.toHaveBeenCalled();
    expect(await screen.findByTestId('sheet-add-lot')).toBeTruthy();
    expect(screen.getByText('Đưa Cà chua vào kho')).toBeTruthy();

    await fireEvent.changeText(screen.getByTestId('qty-grams'), '250');
    await waitFor(() => {
      expect(screen.getByTestId('add-lot-submit').props.accessibilityState?.disabled).toBeFalsy();
    });
    await fireEvent.press(screen.getByTestId('add-lot-submit'));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith(
        '/shopping-items/{id}/to-pantry',
        expect.objectContaining({
          params: { path: { id: 'shop-2' } },
          body: expect.objectContaining({ qty_g: 250 }),
        }),
      );
    });
    expect(await screen.findByText('Đã thêm Cà chua vào Kho bếp')).toBeTruthy();
  });

  it('summarizes partial failure when batch moving bought items to pantry', async () => {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/shopping-items') {
        return okRes({
          items: [
            {
              id: 'b1',
              ingredient_id: 'ing-1',
              ingredient_name_vi: 'Trứng gà',
              qty_g: 180,
              status: 'bought',
              note: null,
              source_meal_plan_item_id: null,
            },
            {
              id: 'b2',
              ingredient_id: 'ing-2',
              ingredient_name_vi: 'Đậu phụ',
              qty_g: 200,
              status: 'bought',
              note: null,
              source_meal_plan_item_id: null,
            },
          ],
        });
      }
      if (path === '/catalog/snapshot') return okRes({ ingredients: [], recipes: [] });
      if (path === '/reference') return okRes({ qty_levels: [], cooking_methods: [], food_groups: [], allergen_groups: [] });
      return okRes({});
    });

    mockedPost.mockImplementation(async (_path: string, opts?: { params?: { path?: { id?: string } } }) => {
      if (opts?.params?.path?.id === 'b1') return okRes({ lot: { id: 'lot-b1' } });
      return errRes(422, { code: 'validation_error' });
    });

    await renderWithProviders(<Shopping />);

    const batchBtn = await screen.findByText('Đưa tất cả vào kho');
    await fireEvent.press(batchBtn);

    expect(await screen.findByText('Đã đưa 1 món vào Kho bếp, 1 món chưa đưa được.')).toBeTruthy();
  });

  it('paginates /shopping-items past 100 items via next_cursor, validates AddSheet qty > 0, and resets error on fallback', async () => {
    const page1 = Array.from({ length: 100 }, (_, idx) => ({
      id: `p1-${idx}`,
      ingredient_id: `ing-${idx}`,
      ingredient_name_vi: `Món ${idx}`,
      qty_g: 100,
      status: 'open' as const,
      note: null,
      source_meal_plan_item_id: null,
    }));
    const page2 = [
      {
        id: 'p2-fail',
        ingredient_id: 'ing-fail',
        ingredient_name_vi: 'Củ cải trắng',
        qty_g: 150,
        status: 'open' as const,
        note: null,
        source_meal_plan_item_id: null,
      },
      {
        id: 'p2-null',
        ingredient_id: 'ing-null',
        ingredient_name_vi: 'Hành tím',
        qty_g: null,
        status: 'open' as const,
        note: null,
        source_meal_plan_item_id: null,
      },
    ];

    mockedGet.mockImplementation(async (path: string, opts?: { params?: { query?: { cursor?: string } } }) => {
      if (path === '/shopping-items') {
        const cursor = opts?.params?.query?.cursor;
        if (!cursor) return okRes({ items: page1, next_cursor: 'cur-2' });
        return okRes({ items: page2, next_cursor: null });
      }
      if (path === '/catalog/snapshot') return okRes({ ingredients: [], recipes: [] });
      if (path === '/reference') return okRes({ qty_levels: [], cooking_methods: [], food_groups: [], allergen_groups: [] });
      if (path === '/ingredients') return okRes({ items: [] });
      return okRes({});
    });

    await renderWithProviders(<Shopping />);
    expect(await screen.findByTestId('shop-item-Hành tím')).toBeTruthy();

    // Previous 500 error from toPantry is cleared cleanly when opening fallback AddLotSheet
    mockedPost.mockResolvedValueOnce(errRes(500, { code: 'internal_error' }));
    await fireEvent.press(screen.getByTestId('shop-to-pantry-Củ cải trắng'));
    expect(await screen.findByText(/Thử lại|không lường trước|hệ thống/i)).toBeTruthy();

    await fireEvent.press(screen.getByTestId('shop-to-pantry-Hành tím'));
    expect(await screen.findByTestId('sheet-add-lot')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    await fireEvent.press(screen.getByLabelText('Đóng'));

    // AddSheet rejects <= 0 qty without posting
    mockedPost.mockClear();
    await fireEvent.press(screen.getByTestId('shop-add'));
    const gramsField = await screen.findByLabelText('Khoảng bao nhiêu gam (không bắt buộc)');
    await fireEvent.changeText(gramsField, '0');
    expect(screen.getByText('Khối lượng phải lớn hơn 0 gam.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Thêm' }).props.accessibilityState?.disabled).toBe(true);
    expect(mockedPost).not.toHaveBeenCalled();
  });
});
