import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';
import React from 'react';

import { api } from '@/api/client';
import AdminConsole from '@/app/quan-tri';

import { mockSessionState } from '../../jest.setup';
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

describe('quan-tri (AdminConsole)', () => {
  beforeEach(() => {
    setWindowWidth(1280, 900);
    mockedGet.mockReset();
    mockedPost.mockReset();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it.each(['user', 'curator'] as const)(
    'renders screen-admin-forbidden for role=%s with 0 /admin/* API calls',
    async (role) => {
      mockSessionState.status = 'signedIn';
      mockSessionState.user = { id: 'u1', email: 'u@tastoria.vn', role, onboarding_completed: true };

      await renderWithProviders(<AdminConsole />);

      expect(screen.getByTestId('screen-admin-forbidden')).toBeTruthy();
      expect(screen.queryByTestId('screen-admin')).toBeNull();
      const adminCalls = mockedGet.mock.calls.filter(([p]) => String(p).startsWith('/admin/'));
      expect(adminCalls).toHaveLength(0);
    },
  );

  it('renders only DSR & Audit tabs for role=admin and resolves manual DSR', async () => {
    mockSessionState.status = 'signedIn';
    mockSessionState.user = { id: 'adm-1', email: 'admin@tastoria.vn', role: 'admin', onboarding_completed: true };

    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/admin/data-requests') {
        return okRes({
          items: [
            {
              id: 'dsr-1',
              type: 'correct',
              status: 'received',
              subject_ref: 'abcdef1234567890abcdef12',
              received_at: '2026-11-18T10:00:00Z',
              due_at: '2026-11-25T10:00:00Z',
              note: 'Sửa cân nặng hồ sơ',
            },
          ],
          next_cursor: null,
        });
      }
      if (path === '/admin/audit-log') {
        return okRes({
          items: [
            {
              id: 'aud-1',
              action: 'dsr_resolve',
              entity: 'dsr_requests',
              entity_id: 'dsr-1',
              actor_role: 'admin',
              request_id: 'req-99',
              created_at: '2026-11-18T11:00:00Z',
            },
          ],
          next_cursor: null,
        });
      }
      return okRes({});
    });
    mockedPost.mockResolvedValueOnce(okRes({ id: 'dsr-1', status: 'completed' }));

    await renderWithProviders(<AdminConsole />);

    expect(screen.getByTestId('screen-admin')).toBeTruthy();
    expect(screen.getByTestId('admin-tab-data-requests')).toBeTruthy();
    expect(screen.getByTestId('admin-tab-audit-log')).toBeTruthy();
    expect(screen.queryByTestId('admin-tab-models')).toBeNull();
    expect(screen.queryByTestId('admin-tab-surveys')).toBeNull();

    const resolveBtn = await screen.findByTestId('dsr-resolve-dsr-1');
    await fireEvent.press(resolveBtn);

    await fireEvent.changeText(screen.getByTestId('dsr-resolve-note'), 'Đã cập nhật dữ liệu');
    await fireEvent.press(screen.getByTestId('dsr-resolve-submit'));

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith('/admin/data-requests/{id}/resolve', {
        params: { path: { id: 'dsr-1' } },
        body: { status: 'completed', note: 'Đã cập nhật dữ liệu' },
      });
    });

    await fireEvent.press(screen.getByTestId('admin-tab-audit-log'));
    expect(await screen.findByText('dsr_resolve (dsr_requests)')).toBeTruthy();

    const forbiddenEndpoints = mockedGet.mock.calls.filter(
      ([p]) => p === '/admin/models' || p === '/admin/surveys',
    );
    expect(forbiddenEndpoints).toHaveLength(0);
  });

  it('renders only Models & Surveys tabs for role=ml_operator', async () => {
    mockSessionState.status = 'signedIn';
    mockSessionState.user = { id: 'ml-1', email: 'ml@tastoria.vn', role: 'ml_operator', onboarding_completed: true };

    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/admin/models') {
        return okRes({
          deployments: [{ name: 'detector', active_version_id: 'mv-1', switched_at: '2026-11-18T09:00:00Z' }],
          items: [
            {
              id: 'mv-1',
              name: 'detector',
              version: '2.0.0',
              status: 'validated',
              is_active: true,
              sha256: '1234567890abcdef',
              preprocess_version: '640px',
              metrics: { mAP50: 0.512 },
            },
          ],
          next_cursor: null,
        });
      }
      if (path === '/admin/surveys') {
        return okRes({
          items: [
            {
              id: 'sv-1',
              version: 'v1',
              is_open: true,
              n_anchor: 10,
              n_random: 35,
              respondents_completed: 24,
              respondents_total: 40,
              created_at: '2026-11-18T08:00:00Z',
            },
          ],
          next_cursor: null,
        });
      }
      return okRes({});
    });

    const view = await renderWithProviders(<AdminConsole />);

    expect(screen.getByTestId('screen-admin')).toBeTruthy();
    expect(screen.getByTestId('admin-tab-models')).toBeTruthy();
    expect(screen.getByTestId('admin-tab-surveys')).toBeTruthy();
    expect(screen.queryByTestId('admin-tab-data-requests')).toBeNull();
    expect(screen.queryByTestId('admin-tab-audit-log')).toBeNull();

    expect(await screen.findByText('detector (2.0.0)')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('admin-tab-surveys'));
    expect(await screen.findByText('Phiên bản v1')).toBeTruthy();

    const forbiddenEndpoints = mockedGet.mock.calls.filter(
      ([p]) => p === '/admin/data-requests' || p === '/admin/audit-log',
    );
    expect(forbiddenEndpoints).toHaveLength(0);
    view.unmount();
    view.queryClient.clear();
  });

  it('renders all 7 models, candidate/rejected/retired labels, nested metrics cleanly, and keeps deployments across filter', async () => {
    mockSessionState.status = 'signedIn';
    mockSessionState.user = { id: 'ml-1', email: 'ml@tastoria.vn', role: 'ml_operator', onboarding_completed: true };

    mockedGet.mockImplementation(async (path: string, opts?: { params?: { query?: { name?: string } } }) => {
      if (path === '/admin/models') {
        const filterName = opts?.params?.query?.name;
        const allItems = [
          {
            id: 'mv-det',
            name: 'detector',
            version: '2.1.0',
            status: 'validated',
            is_active: true,
            sha256: 'aaaa111122223333',
            preprocess_version: '640px',
            metrics: { mAP50: 0.512, per_class: { top1: 0.88, f1: 0.85 } },
          },
          {
            id: 'mv-dish',
            name: 'dish_classifier',
            version: '1.0.0',
            status: 'candidate',
            is_active: false,
            sha256: 'bbbb111122223333',
            preprocess_version: null,
            metrics: { top1: 0.79 },
          },
          {
            id: 'mv-mush',
            name: 'mushroom_classifier',
            version: '1.2.0',
            status: 'rejected',
            is_active: false,
            sha256: 'cccc111122223333',
            preprocess_version: null,
            metrics: null,
          },
          {
            id: 'mv-cal',
            name: 'meal_calorie',
            version: '0.9.0',
            status: 'retired',
            is_active: false,
            sha256: 'dddd111122223333',
            preprocess_version: null,
            metrics: null,
          },
        ];
        return okRes({
          deployments: [
            { name: 'detector', active_version_id: 'mv-det', switched_at: '2026-11-18T09:00:00Z' },
            { name: 'mushroom_classifier', active_version_id: 'mv-mush', switched_at: '2026-11-18T09:00:00Z' },
          ],
          items: filterName ? allItems.filter((x) => x.name === filterName) : allItems,
          next_cursor: null,
        });
      }
      if (path === '/admin/surveys') return okRes({ items: [], next_cursor: null });
      return okRes({});
    });

    const view = await renderWithProviders(<AdminConsole />);

    for (const modelName of [
      'detector',
      'freshness',
      'ranker',
      'substitution',
      'meal_calorie',
      'dish_classifier',
      'mushroom_classifier',
    ]) {
      expect(await screen.findByTestId(`model-deploy-card-${modelName}`)).toBeTruthy();
    }

    // All 4 backend ModelStatus values map cleanly without [object Object]
    expect(screen.getByText('Ứng viên')).toBeTruthy();
    expect(screen.getByText('Đã kiểm định')).toBeTruthy();
    expect(screen.getByText('Bị từ chối')).toBeTruthy();
    expect(screen.getByText('Ngừng dùng')).toBeTruthy();
    expect(screen.queryByText(/object Object/)).toBeNull();
    expect(screen.getByText(/per_class: top1: 0\.88, f1: 0\.85/)).toBeTruthy();

    // Filtering to mushroom_classifier keeps detector's active deployment version cached on its card
    await fireEvent.press(screen.getByRole('checkbox', { name: 'mushroom_classifier' }));
    await waitFor(() => {
      expect(screen.queryByText('detector (2.1.0)')).toBeNull();
      expect(screen.getByText('mushroom_classifier (1.2.0)')).toBeTruthy();
      expect(screen.getByText('v2.1.0')).toBeTruthy();
    });
    view.unmount();
    view.queryClient.clear();
  });

  it('debounces and UUID-validates actor_user_id before calling /admin/audit-log', async () => {
    jest.useFakeTimers();
    try {
      mockSessionState.status = 'signedIn';
      mockSessionState.user = { id: 'adm-1', email: 'admin@tastoria.vn', role: 'admin', onboarding_completed: true };
      mockedGet.mockImplementation(async (path: string) => {
        if (path === '/admin/data-requests') return okRes({ items: [], next_cursor: null });
        if (path === '/admin/audit-log') return okRes({ items: [], next_cursor: null });
        return okRes({});
      });

      const view = await renderWithProviders(<AdminConsole />);
      await fireEvent.press(screen.getByTestId('admin-tab-audit-log'));
      await waitFor(() => {
        expect(mockedGet.mock.calls.some(([p]) => p === '/admin/audit-log')).toBe(true);
      });

      const callsBefore = mockedGet.mock.calls.filter(([p]) => p === '/admin/audit-log').length;
      await fireEvent.changeText(screen.getByTestId('audit-actor-filter'), 'not-a-uuid');
      expect(screen.getByText(/Mã định danh không hợp lệ/)).toBeTruthy();

      await act(async () => {
        jest.advanceTimersByTime(400);
      });
      const callsAfterInvalid = mockedGet.mock.calls.filter(([p]) => p === '/admin/audit-log').length;
      expect(callsAfterInvalid).toBe(callsBefore);

      const validUuid = '12345678-1234-4234-8234-1234567890ab';
      await fireEvent.changeText(screen.getByTestId('audit-actor-filter'), validUuid);
      await act(async () => {
        jest.advanceTimersByTime(400);
      });

      await waitFor(() => {
        const auditCalls = mockedGet.mock.calls.filter(([p]) => p === '/admin/audit-log');
        const lastQ = auditCalls[auditCalls.length - 1]?.[1]?.params?.query;
        expect(lastQ?.actor_user_id).toBe(validUuid);
      });

      view.unmount();
      view.queryClient.clear();
    } finally {
      jest.useRealTimers();
    }
  });
});
