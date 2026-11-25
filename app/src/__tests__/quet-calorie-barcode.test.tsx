import AsyncStorage from '@react-native-async-storage/async-storage';
import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import * as ImagePicker from 'expo-image-picker';
import React from 'react';

import { api } from '@/api/client';
import Scan from '@/app/quet/index';
import * as imageLib from '@/lib/image';
import { listQuickMealLogs } from '@/lib/mealLog';

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
const mockedPost = api.POST as jest.Mock;

describe('Scan triple-mode (Món ăn & Calo + Mã vạch)', () => {
  beforeEach(async () => {
    setWindowWidth(1280, 900);
    mockedGet.mockReset();
    mockedPost.mockReset();
    await AsyncStorage.clear();
  });

  function setupDefaultGets() {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/me/consents') return okRes({ items: [] });
      if (path === '/me/profile') return okRes({ kcal_target: 2000 });
      if (path === '/meal-calorie/dishes') {
        return okRes({
          data_version: 'v1',
          calibrated: true,
          half_width_rel: 0.12,
          dishes: [
            {
              slug: 'mi_hao_hao_tom_chua_cay',
              name_vi: 'Mì Hảo Hảo tôm chua cay (1 gói 75g)',
              slot: 'man',
              kcal_per_serving: 350.0,
              protein_g: 6.9,
              carbs_g: 51.4,
              fat_g: 13.0,
              fiber_g: 2.0,
            },
          ],
        });
      }
      if (path === '/meal-calorie/barcode/{barcode}') {
        return okRes({
          barcode: '8934563138165',
          product_name: 'Mì Hảo Hảo Tôm Chua Cay (gói 75g–77g)',
          brand: 'Acecook / Hảo Hảo',
          serving_size: '1 gói (75g)',
          serving_g: 75,
          kcal_per_serving: 350,
          protein_g_per_serving: 6.9,
          carbs_g_per_serving: 51.4,
          fat_g_per_serving: 13.0,
          fiber_g_per_serving: 2.0,
          kcal_per_100g: 466.7,
          protein_g_per_100g: 9.2,
          carbs_g_per_100g: 68.5,
          fat_g_per_100g: 17.3,
          fiber_g_per_100g: 2.7,
          nutrition_score: 52,
          nutrition_grade: 'C',
          source: 'Mỹ Vị VN Label Catalog',
        });
      }
      return okRes({});
    });
  }

  it('estimates meal calorie via quick search including Mì Hảo Hảo and switches to barcode lookup without leaked jargon', async () => {
    setupDefaultGets();

    mockedPost.mockResolvedValueOnce(
      okRes({
        dish_name_vi: 'Mì Hảo Hảo tôm chua cay (1 gói 75g)',
        portion: 'vua',
        portion_multiplier: 1.0,
        estimated_kcal: 350.0,
        kcal_low: 280.0,
        kcal_high: 420.0,
        protein_g: 6.9,
        carbs_g: 51.4,
        fat_g: 13.0,
        fiber_g: 2.0,
        source: 'onnx_nutrition5k',
        calibrated: false,
        half_width_rel: 0.2,
        latency_ms: 1.2,
        nutrition_score: 55,
        nutrition_grade: 'C',
        domain_shift_note: `Ước lượng trực quan ${'Nutrition' + '5k'} tham chiếu`,
        top_candidates: [],
      }),
    );

    await renderWithProviders(<Scan />);

    // Switch to Món ăn & Calo tab
    await fireEvent.press(screen.getByText('Món ăn & Calo'));
    expect(await screen.findByTestId('scan-calorie-panel')).toBeTruthy();

    await fireEvent.press(screen.getByText('Mì Hảo Hảo'));
    expect(await screen.findByTestId('calorie-result-card')).toBeTruthy();
    expect(screen.getByTestId('macro-pie-chart')).toBeTruthy();
    expect(screen.getByText('350 kcal')).toBeTruthy();
    expect(screen.getByTestId('calorie-range-bar')).toBeTruthy();
    expect(screen.getByText('Năng lượng vừa')).toBeTruthy();
    expect(screen.queryByText(/Chỉ số dinh dưỡng Mỹ Vị/)).toBeNull();
    expect(screen.queryByText(/\/100/)).toBeNull();
    expect(screen.queryByText(/Độ tin cậy/)).toBeNull();
    expect(screen.queryByText(new RegExp('nutrition' + '5k', 'i'))).toBeNull();

    // Switch to Mã vạch tab
    await fireEvent.press(screen.getByText('Mã vạch'));
    expect(await screen.findByTestId('scan-barcode-panel')).toBeTruthy();

    await fireEvent.changeText(screen.getByTestId('barcode-input'), '8934563138165');
    await fireEvent.press(screen.getByTestId('barcode-lookup-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('barcode-result-card')).toBeTruthy();
    });
    expect(screen.getByTestId('macro-pie-chart')).toBeTruthy();
    expect(screen.getByText('350 kcal / phần')).toBeTruthy();
    expect(screen.getByText('Mì Hảo Hảo Tôm Chua Cay (gói 75g–77g)')).toBeTruthy();
    expect(screen.getByText('Năng lượng vừa')).toBeTruthy();
    expect(screen.queryByText(new RegExp('yu' + 'ka', 'i'))).toBeNull();
  });

  it('shows Top-2 disambiguation banner, toggles VN modifiers live, and logs meal to quick journal with undo', async () => {
    setupDefaultGets();

    mockedPost
      .mockResolvedValueOnce(
        okRes({
          dish_name_vi: 'Cơm tấm sườn bì chả',
          recognized_dish_id: 'com_tam',
          recognized_confidence: 0.44,
          disambiguation_required: true,
          top_margin: 0.07,
          provenance_label_vi: 'Viện Dinh dưỡng VN & Ảnh',
          portion: 'vua',
          portion_multiplier: 1.0,
          estimated_kcal: 350.0,
          kcal_low: 300.0,
          kcal_high: 400.0,
          protein_g: 22.0,
          carbs_g: 42.0,
          fat_g: 10.0,
          fiber_g: 2.0,
          source: 'hybrid',
          calibrated: true,
          half_width_rel: 0.14,
          latency_ms: 8.5,
          top_candidates: [
            { dish_id: 'com_tam', name_vi: 'Cơm tấm sườn bì chả', name_en: 'Broken rice', confidence: 0.44, kcal_vua: 350 },
            { dish_id: 'bun_thit_nuong', name_vi: 'Bún thịt nướng', name_en: 'Grilled pork vermicelli', confidence: 0.37, kcal_vua: 490 },
          ],
        }),
      )
      .mockResolvedValueOnce(
        okRes({
          dish_name_vi: 'Bún thịt nướng',
          recognized_dish_id: 'bun_thit_nuong',
          recognized_confidence: 0.86,
          disambiguation_required: false,
          top_margin: 0.4,
          provenance_label_vi: 'Viện Dinh dưỡng VN & Ảnh',
          portion: 'vua',
          portion_multiplier: 1.0,
          estimated_kcal: 490.0,
          kcal_low: 440.0,
          kcal_high: 540.0,
          protein_g: 26.0,
          carbs_g: 58.0,
          fat_g: 16.0,
          fiber_g: 3.0,
          source: 'hybrid',
          calibrated: true,
          half_width_rel: 0.1,
          latency_ms: 6.1,
          top_candidates: [],
        }),
      );

    await renderWithProviders(<Scan />);
    await fireEvent.press(screen.getByText('Món ăn & Calo'));
    await fireEvent.press(screen.getByText('Cơm tấm'));

    expect(await screen.findByTestId('calorie-disambiguation-banner')).toBeTruthy();
    expect(screen.getByText(/Ảnh có thể là Bún thịt nướng/)).toBeTruthy();

    // Tap candidate #2 in disambiguation banner
    await fireEvent.press(screen.getByText('Bún thịt nướng (490 kcal)'));
    await waitFor(() => {
      expect(screen.getByText('490 kcal')).toBeTruthy();
    });

    // Toggle VN modifier (+80 kcal) -> 570 kcal live
    await fireEvent.press(screen.getByTestId('modifier-mo_hanh'));
    expect(screen.getByText('570 kcal')).toBeTruthy();

    // 1-tap Ghi vào Nhật ký hôm nay
    await fireEvent.press(screen.getByTestId('calorie-log-to-journal'));
    expect(await screen.findByTestId('calorie-logged-notice')).toBeTruthy();

    const saved = await listQuickMealLogs('user-1');
    expect(saved).toHaveLength(1);
    expect(saved[0].title_vi).toBe('Bún thịt nướng');
    expect(saved[0].kcal).toBe(570);
    expect(saved[0].modifiers_vi[0]).toContain('Thêm mỡ hành');

    // Undo removes entry
    await fireEvent.press(screen.getByText('Hoàn tác'));
    await waitFor(async () => {
      const afterUndo = await listQuickMealLogs('user-1');
      expect(afterUndo).toHaveLength(0);
    });
  });

  it('clears stale dishQuery when pickMealPhoto runs and preserves active modifiers across portion change', async () => {
    setupDefaultGets();

    const sentForms: FormData[] = [];
    mockedPost.mockImplementation(async (_path: string, opts: { bodySerializer?: () => FormData }) => {
      if (opts?.bodySerializer) sentForms.push(opts.bodySerializer());
      return okRes({
        dish_name_vi: 'Phở bò',
        recognized_dish_id: 'pho_bo',
        recognized_confidence: 0.9,
        disambiguation_required: false,
        top_margin: 0.5,
        provenance_label_vi: 'Viện Dinh dưỡng VN & Ảnh',
        portion: 'vua',
        portion_multiplier: 1.0,
        estimated_kcal: 450,
        kcal_low: 400,
        kcal_high: 500,
        protein_g: 25,
        carbs_g: 55,
        fat_g: 12,
        fiber_g: 2,
        source: 'hybrid',
        calibrated: true,
        half_width_rel: 0.11,
        latency_ms: 5,
        top_candidates: [],
      });
    });

    (ImagePicker.launchImageLibraryAsync as jest.Mock).mockResolvedValueOnce({
      canceled: false,
      assets: [{ uri: 'file:///mock-pho.jpg', width: 800, height: 600 }],
    });

    const imgPartSpy = jest.spyOn(imageLib, 'imagePart').mockResolvedValue(new Blob(['jpeg'], { type: 'image/jpeg' }));

    try {
      await renderWithProviders(<Scan />);
      await fireEvent.press(screen.getByText('Món ăn & Calo'));

      // Step 1: search Mì Hảo Hảo first
      await fireEvent.press(screen.getByText('Mì Hảo Hảo'));
      expect(await screen.findByTestId('calorie-result-card')).toBeTruthy();

      // Step 2: pick a new meal photo -> must clear dishQuery and NOT send stale dish_name
      await fireEvent.press(screen.getByTestId('calorie-library'));
      await waitFor(() => {
        expect(sentForms).toHaveLength(2);
      });
      expect(sentForms[1].get('dish_name')).toBeNull();
      expect(sentForms[1].get('image')).toBeTruthy();

      // Step 3: toggle modifier (+80 kcal) -> 530 kcal, then switch portion to Lớn 1.35× -> modifier stays active!
      await fireEvent.press(screen.getByTestId('modifier-mo_hanh'));
      expect(screen.getByText('530 kcal')).toBeTruthy();

      await fireEvent.press(screen.getByText('Lớn 1.35×'));
      await waitFor(() => {
        expect(sentForms).toHaveLength(3);
      });
      expect(screen.getByText('530 kcal')).toBeTruthy();
    } finally {
      imgPartSpy.mockRestore();
    }
  });

  it('sends dish_slug on suggestion tap, cancels/ignores stale estimates, disables portions while busy, and guards double-tap log', async () => {
    setupDefaultGets();

    let resolveFirst!: (val: ReturnType<typeof okRes>) => void;
    const forms: FormData[] = [];
    let callIdx = 0;

    mockedPost.mockImplementation(async (path: string, opts?: { bodySerializer?: () => FormData }) => {
      if (path === '/meal-logs') {
        return okRes({
          id: 'srv-log-1',
          user_id: 'user-1',
          logged_at: '2026-11-24T12:00:00Z',
          logged_date: '2026-11-24',
          meal_slot: 'trua',
          title: 'Mì Hảo Hảo tôm chua cay (1 gói 75g)',
          source_type: 'scan_calorie',
          source_ref_id: 'mi_hao_hao_tom_chua_cay',
          portion_label: 'Vừa 1.0×',
          portion_scale: 1,
          modifiers: [],
          kcal: 350,
          kcal_low: 310,
          kcal_high: 390,
          protein_g: 7,
          carbs_g: 51,
          fat_g: 13,
          fiber_g: 2,
          provenance_label_vi: 'Viện Dinh dưỡng Quốc gia & Ảnh',
          items: [],
        });
      }
      if (opts?.bodySerializer) forms.push(opts.bodySerializer());
      callIdx += 1;
      if (callIdx === 1) {
        return new Promise((res) => {
          resolveFirst = res as unknown as (val: ReturnType<typeof okRes>) => void;
        });
      }
      return okRes({
        dish_name_vi: 'Mì Hảo Hảo tôm chua cay (1 gói 75g)',
        kb_slug: 'mi_hao_hao_tom_chua_cay',
        portion: 'vua',
        portion_multiplier: 1.0,
        estimated_kcal: 350,
        kcal_low: 310,
        kcal_high: 390,
        protein_g: 7,
        carbs_g: 51,
        fat_g: 13,
        fiber_g: 2,
        source: 'kb',
        calibrated: true,
        half_width_rel: 0.1,
        latency_ms: 4,
        top_candidates: [],
      });
    });

    await renderWithProviders(<Scan />);
    await fireEvent.press(screen.getByText('Món ăn & Calo'));

    // First slow request (via quick search Cơm tấm) stays pending while suggestion tap supersedes it
    await fireEvent.press(screen.getByText('Cơm tấm'));
    await fireEvent.changeText(screen.getByTestId('calorie-search-input'), 'Hảo Hảo');
    const sug = await screen.findByTestId('calorie-suggestion-mi_hao_hao_tom_chua_cay');
    await fireEvent.press(sug);

    expect(await screen.findByText('350 kcal')).toBeTruthy();
    expect(forms[1].get('dish_slug')).toBe('mi_hao_hao_tom_chua_cay');

    // Late stale first response resolves with 999 kcal -> must be ignored!
    resolveFirst(
      okRes({
        dish_name_vi: 'Cơm tấm cũ',
        portion: 'vua',
        portion_multiplier: 1,
        estimated_kcal: 999,
        kcal_low: 900,
        kcal_high: 1100,
        protein_g: 30,
        carbs_g: 100,
        fat_g: 40,
        fiber_g: 2,
        source: 'hybrid',
        calibrated: true,
        half_width_rel: 0.1,
        latency_ms: 5,
        top_candidates: [],
      }),
    );
    await waitFor(() => {
      expect(screen.queryByText('999 kcal')).toBeNull();
    });
    expect(screen.getByText('350 kcal')).toBeTruthy();

    // Slow meal-logs POST prevents duplicate double-tap writes
    let resolveLog!: (val: ReturnType<typeof okRes>) => void;
    mockedPost.mockImplementationOnce(
      () =>
        new Promise((res) => {
          resolveLog = res as unknown as (val: ReturnType<typeof okRes>) => void;
        }),
    );
    const logBtn = screen.getByTestId('calorie-log-to-journal');
    await fireEvent.press(logBtn);
    expect(screen.getByTestId('calorie-log-to-journal').props.accessibilityState?.disabled).toBe(true);
    await fireEvent.press(screen.getByTestId('calorie-log-to-journal'));

    const mealLogPosts = mockedPost.mock.calls.filter(([p]) => p === '/meal-logs');
    expect(mealLogPosts).toHaveLength(1);

    resolveLog(
      okRes({
        id: 'srv-log-1',
        user_id: 'user-1',
        logged_at: '2026-11-24T12:00:00Z',
        logged_date: '2026-11-24',
        meal_slot: 'trua',
        title: 'Mì Hảo Hảo tôm chua cay (1 gói 75g)',
        source_type: 'scan_calorie',
        source_ref_id: 'mi_hao_hao_tom_chua_cay',
        portion_label: 'Vừa 1.0×',
        portion_scale: 1,
        modifiers: [],
        kcal: 350,
        kcal_low: 310,
        kcal_high: 390,
        protein_g: 7,
        carbs_g: 51,
        fat_g: 13,
        fiber_g: 2,
        provenance_label_vi: 'Viện Dinh dưỡng Quốc gia & Ảnh',
        items: [],
      }),
    );
    expect(await screen.findByTestId('calorie-logged-notice')).toBeTruthy();
  });

  it('clears photo-only estimate on Xoá ảnh, unifies barcode 100g fallback, and checks BarcodeDetector before launching picker', async () => {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/me/consents') return okRes({ items: [] });
      if (path === '/me/profile') return okRes({ kcal_target: 2000 });
      if (path === '/meal-calorie/dishes') return okRes({ data_version: 'v1', calibrated: true, half_width_rel: 0.1, dishes: [] });
      if (path === '/meal-calorie/barcode/{barcode}') {
        return okRes({
          barcode: '8930000000011',
          product_name: 'Sữa hạt đóng hộp',
          brand: null,
          serving_size: null,
          serving_g: null,
          kcal_per_serving: null,
          protein_g_per_serving: null,
          carbs_g_per_serving: null,
          fat_g_per_serving: null,
          fiber_g_per_serving: null,
          kcal_per_100g: 250,
          protein_g_per_100g: 8,
          carbs_g_per_100g: 30,
          fat_g_per_100g: 10,
          fiber_g_per_100g: 2,
          nutrition_score: 40,
          nutrition_grade: 'B',
          source: 'Nhãn sản phẩm',
        });
      }
      return okRes({});
    });

    (ImagePicker.launchImageLibraryAsync as jest.Mock).mockResolvedValueOnce({
      canceled: false,
      assets: [{ uri: 'file:///photo-only.jpg', width: 800, height: 600 }],
    });
    const imgPartSpy = jest.spyOn(imageLib, 'imagePart').mockResolvedValue(new Blob(['jpeg'], { type: 'image/jpeg' }));
    mockedPost.mockResolvedValueOnce(
      okRes({
        dish_name_vi: 'Bún riêu',
        portion: 'vua',
        portion_multiplier: 1,
        estimated_kcal: 410,
        kcal_low: 360,
        kcal_high: 460,
        protein_g: 20,
        carbs_g: 50,
        fat_g: 14,
        fiber_g: 2,
        source: 'hybrid',
        calibrated: true,
        half_width_rel: 0.12,
        latency_ms: 4,
        top_candidates: [],
      }),
    );

    try {
      await renderWithProviders(<Scan />);
      await fireEvent.press(screen.getByText('Món ăn & Calo'));
      await fireEvent.press(screen.getByTestId('calorie-library'));
      expect(await screen.findByTestId('calorie-result-card')).toBeTruthy();

      await fireEvent.press(screen.getByTestId('calorie-remove-image'));
      await waitFor(() => {
        expect(screen.queryByTestId('calorie-result-card')).toBeNull();
      });

      // Barcode photo scan launches picker and falls back cleanly to POST /meal-calorie/barcode-image when BarcodeDetector is absent
      await fireEvent.press(screen.getByText('Mã vạch'));
      (ImagePicker.launchImageLibraryAsync as jest.Mock).mockResolvedValueOnce({
        canceled: false,
        assets: [{ uri: 'file:///barcode-photo.jpg', width: 800, height: 600 }],
      });
      mockedPost.mockResolvedValueOnce(
        okRes({
          barcode: '8930000000011',
          product_name: 'Sữa hạt đóng hộp',
          brand: null,
          serving_size: null,
          serving_g: null,
          kcal_per_serving: null,
          protein_g_per_serving: null,
          carbs_g_per_serving: null,
          fat_g_per_serving: null,
          fiber_g_per_serving: null,
          kcal_per_100g: 250,
          protein_g_per_100g: 8,
          carbs_g_per_100g: 30,
          fat_g_per_100g: 10,
          fiber_g_per_100g: 2,
          nutrition_score: 40,
          nutrition_grade: 'B',
          source: 'Nhãn sản phẩm',
        }),
      );
      await fireEvent.press(screen.getByTestId('barcode-photo-btn'));
      expect(await screen.findByTestId('barcode-result-card')).toBeTruthy();
      expect(screen.getByText('250 kcal / 100g')).toBeTruthy();

      await fireEvent.press(screen.getByTestId('barcode-log-to-journal'));
      expect(await screen.findByTestId('barcode-logged-notice')).toBeTruthy();
      const logs = await listQuickMealLogs('user-1');
      expect(logs[0]?.kcal).toBe(250);
      expect(logs[0]?.portion_label).toBe('100 g');
    } finally {
      imgPartSpy.mockRestore();
    }
  });

  it('renders detected_plates multi-dish panel and updates live kcal when plates are toggled', async () => {
    setupDefaultGets();
    mockedPost.mockResolvedValueOnce(
      okRes({
        dish_name_vi: 'Bún thịt nướng',
        portion: 'vua',
        portion_multiplier: 1.0,
        estimated_kcal: 800,
        kcal_low: 680,
        kcal_high: 920,
        protein_g: 30,
        carbs_g: 90,
        fat_g: 28,
        fiber_g: 4,
        source: 'hybrid',
        calibrated: true,
        half_width_rel: 0.15,
        latency_ms: 9,
        top_candidates: [],
        detected_plates: [
          { label: 'plate_1', confidence: 0.91, x1: 0.1, y1: 0.1, x2: 0.5, y2: 0.5, dish_id: 'cha_gio_ran', dish_name_vi: 'Chả giò rán', estimated_kcal_vua: 410 },
          { label: 'plate_2', confidence: 0.87, x1: 0.5, y1: 0.1, x2: 0.9, y2: 0.5, dish_id: 'banh_hoi', dish_name_vi: 'Bánh hỏi', estimated_kcal_vua: 390 },
        ],
      }),
    );

    await renderWithProviders(<Scan />);
    await fireEvent.press(screen.getByText('Món ăn & Calo'));
    await fireEvent.press(screen.getByText('Bún thịt nướng'));

    expect(await screen.findByTestId('detected-plates-panel')).toBeTruthy();
    expect(screen.getByText('800 kcal')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('detected-plate-1'));
    expect(screen.getByText('410 kcal')).toBeTruthy();
  });
});
