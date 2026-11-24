import { StyleSheet } from 'react-native';
import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import React from 'react';

import { api } from '@/api/client';
import ConfirmScan from '@/app/quet/[id]';

import { mockNavState } from '../../jest.setup';
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

function makeScan(classifierVersionId: string | null) {
  return {
    id: 'scan-1',
    mode: 'fridge',
    status: 'done',
    classifier_version_id: classifierVersionId,
    images: [{ ordinal: 1, width: 800, height: 600, purged: false }],
    items: [
      {
        id: 'si-user',
        ingredient_id: 'ing-hanh',
        ingredient_name_vi: 'Hành lá',
        origin: 'user_added',
        predicted_freshness: null,
        user_freshness: null,
        needs_check: false,
        final_count: null,
        model_count: null,
        qty_level: 'vua',
        user_action: 'confirmed',
        detections: [],
      },
      {
        id: 'si-single',
        ingredient_id: 'ing-cachua',
        ingredient_name_vi: 'Cà chua',
        origin: 'model',
        predicted_freshness: 'tuoi',
        user_freshness: null,
        needs_check: false,
        final_count: 3,
        model_count: 3,
        qty_level: null,
        user_action: 'confirmed',
        detections: [
          {
            id: 101,
            image_ordinal: 1,
            x1: 0.1,
            y1: 0.1,
            x2: 0.4,
            y2: 0.4,
            confidence: 0.91,
            p_tuoi: 0.72,
            p_dung_som: 0.2,
            p_dung_ngay: 0.05,
            p_kiem_tra: 0.03,
          },
        ],
      },
      {
        id: 'si-multi',
        ingredient_id: 'ing-thit',
        ingredient_name_vi: 'Thịt lợn',
        origin: 'model',
        predicted_freshness: 'kiem_tra',
        user_freshness: null,
        needs_check: true,
        final_count: null,
        model_count: null,
        qty_level: 'vua',
        user_action: 'confirmed',
        detections: [
          {
            id: 201,
            image_ordinal: 1,
            x1: 0.5,
            y1: 0.2,
            x2: 0.8,
            y2: 0.5,
            confidence: 0.84,
            p_tuoi: 0.85,
            p_dung_som: 0.1,
            p_dung_ngay: 0.03,
            p_kiem_tra: 0.02,
          },
          {
            id: 202,
            image_ordinal: 1,
            x1: 0.55,
            y1: 0.55,
            x2: 0.9,
            y2: 0.9,
            confidence: 0.77,
            p_tuoi: 0.05,
            p_dung_som: 0.05,
            p_dung_ngay: 0.25,
            p_kiem_tra: 0.65,
          },
        ],
      },
    ],
  };
}

describe('quet/[id] (ConfirmScan)', () => {
  beforeEach(() => {
    setWindowWidth(1280, 900);
    mockNavState.params = { id: 'scan-1' };
    mockedGet.mockReset();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  function setupApi(classifierVersionId: string | null) {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/scans/{id}') return okRes(makeScan(classifierVersionId));
      if (path === '/scans/{id}/images/{ordinal}') return errRes(410, { code: 'image_purged' });
      if (path === '/reference') return okRes({ food_groups: [], cooking_methods: [], allergen_groups: [], qty_levels: [] });
      if (path === '/catalog/snapshot') return okRes({ ingredients: [], recipes: [] });
      if (path === '/pantry/lots') return okRes({ items: [] });
      return okRes({});
    });
  }

  it('shows 410 image_purged fallback and renders freshness bars for 0, 1, and >1 detections', async () => {
    setupApi('clf-v2-12345678');
    await renderWithProviders(<ConfirmScan />);

    expect(
      await screen.findByText(
        'Ảnh gốc đã được xoá sau 30 ngày theo chính sách lưu trữ. Bạn vẫn có thể sửa và xác nhận nguyên liệu bên dưới.',
      ),
    ).toBeTruthy();
    expect(
      screen.getByText('Hệ thống tự nhận diện rau củ, thịt, cá, trứng, nấm và đồ đóng gói. Món nào thiếu bạn bấm thêm tay ngay bên dưới.'),
    ).toBeTruthy();

    // 0 detections (user_added)
    await fireEvent.press(screen.getByTestId('scan-chip-Hành lá'));
    expect(screen.getByTestId('freshness-prob-bars')).toBeTruthy();
    expect(screen.getByText('Nguyên liệu do bạn tự thêm, chọn độ tươi thủ công.')).toBeTruthy();
    await fireEvent.press(screen.getByLabelText('Đóng'));

    // 1 detection
    await waitFor(() => {
      expect(screen.queryByTestId('sheet-scan-item')).toBeNull();
    });
    await fireEvent.press(screen.getByTestId('scan-chip-Cà chua'));
    expect(screen.getByTestId('freshness-prob-bars')).toBeTruthy();
    expect(screen.getByText('72%')).toBeTruthy();
    expect(screen.getByText('20%')).toBeTruthy();
    expect(screen.getByText('5%')).toBeTruthy();
    expect(screen.getByText('3%')).toBeTruthy();
    expect(screen.queryByText(/clf-v2-1/)).toBeNull();
    await fireEvent.press(screen.getByLabelText('Đóng'));

    // >1 detections: worst-case (#2) selected initially, then switch to #1
    await waitFor(() => {
      expect(screen.queryByTestId('sheet-scan-item')).toBeNull();
    });
    await fireEvent.press(screen.getByTestId('scan-chip-Thịt lợn'));
    expect(screen.getByText('65%')).toBeTruthy();
    expect(screen.getByText('25%')).toBeTruthy();

    await fireEvent.press(screen.getByText('Phát hiện #1'));
    expect(screen.getByText('85%')).toBeTruthy();
    expect(screen.getByText('10%')).toBeTruthy();
  });

  it('shows fallback notice when Scan.classifier_version_id is null', async () => {
    setupApi(null);
    await renderWithProviders(<ConfirmScan />);

    const chip = await screen.findByTestId('scan-chip-Cà chua');
    await fireEvent.press(chip);

    expect(screen.getByTestId('freshness-prob-bars')).toBeTruthy();
    expect(screen.getByText('Chưa có điểm độ tươi tự động, hãy tự kiểm tra.')).toBeTruthy();
  });

  it('displays Direction 1 mushroom sub-species name when sub_species_slug is present', async () => {
    const baseScan = makeScan('clf-v2-12345678');
    const mushroomScan = {
      ...baseScan,
      items: [
        ...baseScan.items,
        {
          id: 'si-nam',
          ingredient_id: 'ing-nam',
          ingredient_name_vi: 'Nấm',
          origin: 'model',
          predicted_freshness: 'tuoi',
          user_freshness: null,
          needs_check: false,
          final_count: null,
          model_count: null,
          qty_level: 'vua',
          user_action: 'kept',
          sub_species_slug: 'nam-rom',
          sub_species_conf: 0.88,
          detections: [
            {
              id: 301,
              image_ordinal: 1,
              x1: 0.2,
              y1: 0.2,
              x2: 0.4,
              y2: 0.4,
              confidence: 0.9,
              sub_species_slug: 'nam-rom',
              sub_species_conf: 0.88,
              p_tuoi: 0.8,
              p_dung_som: 0.1,
              p_dung_ngay: 0.05,
              p_kiem_tra: 0.05,
            },
          ],
        },
      ],
    };
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/scans/{id}') return okRes(mushroomScan);
      if (path === '/scans/{id}/images/{ordinal}') return errRes(410, { code: 'image_purged' });
      if (path === '/reference') return okRes({ food_groups: [], cooking_methods: [], allergen_groups: [], qty_levels: [] });
      if (path === '/catalog/snapshot') return okRes({ ingredients: [], recipes: [] });
      if (path === '/pantry/lots') return okRes({ items: [] });
      return okRes({});
    });

    await renderWithProviders(<ConfirmScan />);
    const chip = await screen.findByTestId('scan-chip-Nấm');
    expect(screen.getByText('Nấm rơm, vừa')).toBeTruthy();

    await fireEvent.press(chip);
    expect(await screen.findByTestId('mushroom-subspecies-badge')).toBeTruthy();
    expect(screen.getByText('Loại nấm nhận diện: Nấm rơm (88%)')).toBeTruthy();
  });

  it('renders generic Nấm and safety abstention note when safety_abstained is true', async () => {
    const baseScan = makeScan('clf-v2-12345678');
    const abstainedScan = {
      ...baseScan,
      items: [
        ...baseScan.items,
        {
          id: 'si-nam-abstain',
          ingredient_id: 'ing-nam',
          ingredient_name_vi: 'Nấm',
          origin: 'model',
          predicted_freshness: 'tuoi',
          user_freshness: null,
          needs_check: false,
          final_count: null,
          model_count: null,
          qty_level: 'vua',
          user_action: 'kept',
          sub_species_slug: null,
          sub_species_conf: null,
          safety_abstained: true,
          safety_note_vi: 'Nấm (chưa rõ loại, chỉ dùng nấm rõ nguồn gốc mua tại chợ hoặc siêu thị)',
          detections: [
            {
              id: 302,
              image_ordinal: 1,
              x1: 0.2,
              y1: 0.2,
              x2: 0.4,
              y2: 0.4,
              confidence: 0.85,
              sub_species_slug: null,
              safety_abstained: true,
            },
          ],
        },
      ],
    };
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/scans/{id}') return okRes(abstainedScan);
      if (path === '/scans/{id}/images/{ordinal}') return errRes(410, { code: 'image_purged' });
      if (path === '/reference') return okRes({ food_groups: [], cooking_methods: [], allergen_groups: [], qty_levels: [] });
      if (path === '/catalog/snapshot') return okRes({ ingredients: [], recipes: [] });
      if (path === '/pantry/lots') return okRes({ items: [] });
      return okRes({});
    });

    await renderWithProviders(<ConfirmScan />);
    const chip = await screen.findByTestId('scan-chip-Nấm');
    expect(screen.getByText('Nấm, vừa')).toBeTruthy();
    expect(screen.getByTestId('mushroom-safety-banner')).toBeTruthy();
    expect(
      screen.getAllByText('Nấm (chưa rõ loại, chỉ dùng nấm rõ nguồn gốc mua tại chợ hoặc siêu thị)').length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId('scan-confirm').props.accessibilityState?.disabled).toBe(true);

    await fireEvent.press(chip);
    expect(await screen.findByTestId('mushroom-safety-note')).toBeTruthy();
    expect(screen.queryByTestId('mushroom-subspecies-badge')).toBeNull();
  });

  it('renders percentage-aligned bounding boxes matching image aspect ratio', async () => {
    const baseScan = makeScan('clf-v2-12345678');
    const wideScan = {
      ...baseScan,
      images: [{ ordinal: 1, width: 640, height: 360, purged: false }],
    };
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/scans/{id}') return okRes(wideScan);
      if (path === '/scans/{id}/images/{ordinal}') return okRes(new Blob(['img'], { type: 'image/jpeg' }));
      if (path === '/reference') return okRes({ food_groups: [], cooking_methods: [], allergen_groups: [], qty_levels: [] });
      if (path === '/catalog/snapshot') return okRes({ ingredients: [], recipes: [] });
      if (path === '/pantry/lots') return okRes({ items: [] });
      return okRes({});
    });

    const origFileReader = globalThis.FileReader;
    const origCreateObjectURL = globalThis.URL?.createObjectURL;
    const origRevokeObjectURL = globalThis.URL?.revokeObjectURL;

    class MockFileReader {
      result: string | null = null;
      onloadend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      readAsDataURL() {
        this.result = 'data:image/jpeg;base64,AA==';
        this.onloadend?.();
      }
    }
    (globalThis as unknown as { FileReader: unknown }).FileReader = MockFileReader;
    if (globalThis.URL) {
      globalThis.URL.createObjectURL = jest.fn(() => 'blob:mock-scan-img');
      globalThis.URL.revokeObjectURL = jest.fn();
    }

    try {
      await renderWithProviders(<ConfirmScan />);
      const overlay = await screen.findByTestId('scan-bbox-overlay');
      expect(overlay).toBeTruthy();

      const box1 = screen.getByTestId('scan-bbox-1');
      expect(StyleSheet.flatten(box1.props.style)).toMatchObject({
        position: 'absolute',
        left: '10%',
        top: '10%',
        width: '30%',
        height: '30%',
      });
      expect(screen.getByText('#1')).toBeTruthy();

      await fireEvent.press(box1);
      expect(await screen.findByTestId('sheet-scan-item')).toBeTruthy();
    } finally {
      (globalThis as unknown as { FileReader: unknown }).FileReader = origFileReader;
      if (globalThis.URL) {
        if (origCreateObjectURL) globalThis.URL.createObjectURL = origCreateObjectURL;
        if (origRevokeObjectURL) globalThis.URL.revokeObjectURL = origRevokeObjectURL;
      }
    }
  });

  it('renders explicit discarded state when scan status is discarded', async () => {
    const discardedScan = { ...makeScan('clf-v2-1'), status: 'discarded' };
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/scans/{id}') return okRes(discardedScan);
      if (path === '/reference') return okRes({ food_groups: [], cooking_methods: [], allergen_groups: [], qty_levels: [] });
      if (path === '/catalog/snapshot') return okRes({ ingredients: [], recipes: [] });
      if (path === '/pantry/lots') return okRes({ items: [] });
      return okRes({});
    });

    await renderWithProviders(<ConfirmScan />);
    expect(await screen.findByTestId('screen-scan-discarded')).toBeTruthy();
    expect(screen.getByText('Đã bỏ lần quét này')).toBeTruthy();
  });

  it('forwards AbortSignal to scan fetch and omits UTC purchase_date on haul confirm', async () => {
    const haulScan = { ...makeScan('clf-v2-1'), mode: 'haul' };
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/scans/{id}') return okRes(haulScan);
      if (path === '/scans/{id}/images/{ordinal}') return errRes(410, { code: 'image_purged' });
      if (path === '/reference') return okRes({ food_groups: [], cooking_methods: [], allergen_groups: [], qty_levels: [] });
      if (path === '/catalog/snapshot') return okRes({ ingredients: [], recipes: [] });
      if (path === '/pantry/lots') return okRes({ items: [] });
      return okRes({});
    });
    mockedPost.mockResolvedValueOnce(okRes({ created_lot_ids: ['lot-1'], not_seen_lot_ids: [] }));

    await renderWithProviders(<ConfirmScan />);
    const confirmBtn = await screen.findByTestId('scan-confirm');

    const scanGetCall = mockedGet.mock.calls.find(([p]) => p === '/scans/{id}');
    expect(scanGetCall?.[1]?.signal).toBeDefined();

    await fireEvent.press(confirmBtn);
    await waitFor(() => expect(mockedPost).toHaveBeenCalled());
    const [postPath, postOpts] = mockedPost.mock.calls[0];
    expect(postPath).toBe('/scans/{id}/confirm');
    expect(postOpts.body).not.toHaveProperty('purchase_date');
  });
});
