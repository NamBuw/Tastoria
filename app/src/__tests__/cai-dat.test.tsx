import { act, fireEvent, screen, waitFor } from '@testing-library/react-native';
import React from 'react';
import { Platform } from 'react-native';

import { api } from '@/api/client';
import Settings from '@/app/cai-dat';

import { mockSessionState } from '../../jest.setup';
import { errRes, okRes, renderWithProviders, setWindowWidth } from './test-utils';

jest.mock('@/api/client', () => {
  const actual = jest.requireActual('@/api/client');
  return {
    ...actual,
    api: {
      GET: jest.fn(),
      POST: jest.fn(),
      PATCH: jest.fn(),
      PUT: jest.fn(),
      DELETE: jest.fn(),
    },
  };
});

const mockedGet = api.GET as jest.Mock;
const mockedPost = api.POST as jest.Mock;
const mockedDelete = api.DELETE as jest.Mock;

describe('cai-dat (Settings Export DSR status, sections & security)', () => {
  const originalPlatform = Platform.OS;

  beforeEach(() => {
    setWindowWidth(1280, 900);
    mockSessionState.status = 'signedIn';
    mockSessionState.user = {
      id: 'user-1',
      email: 'cook@example.vn',
      role: 'user',
      onboarding_completed: true,
    };
    mockedGet.mockReset();
    mockedPost.mockReset();
    mockedDelete.mockReset();
  });

  afterEach(() => {
    Object.defineProperty(Platform, 'OS', { value: originalPlatform, configurable: true });
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it('maps ExportSection in_progress and rejected statuses to Vietnamese via DSR_STATUS_VI', async () => {
    mockedPost.mockResolvedValueOnce(okRes({ id: 'exp-1' }));
    mockedGet.mockResolvedValueOnce(
      okRes({ id: 'exp-1', status: 'in_progress', due_at: '2026-11-25T10:00:00Z', download_available: false }),
    );

    const view = await renderWithProviders(<Settings />);
    await fireEvent.press(screen.getByTestId('settings-export'));
    await fireEvent.press(await screen.findByText('Gửi yêu cầu tải dữ liệu'));

    await waitFor(() => {
      expect(screen.getByText(/Trạng thái: đang xử lý/)).toBeTruthy();
    });
    expect(screen.queryByText(/in_progress/)).toBeNull();
    view.unmount();
    view.queryClient.clear();
  });

  it('maps ExportSection rejected status to Vietnamese via DSR_STATUS_VI', async () => {
    mockedPost.mockResolvedValueOnce(okRes({ id: 'exp-2' }));
    mockedGet.mockResolvedValueOnce(
      okRes({ id: 'exp-2', status: 'rejected', due_at: '2026-11-25T10:00:00Z', download_available: false }),
    );

    const view = await renderWithProviders(<Settings />);
    await fireEvent.press(screen.getByTestId('settings-export'));
    await fireEvent.press(await screen.findByText('Gửi yêu cầu tải dữ liệu'));

    await waitFor(() => {
      expect(screen.getByText(/Trạng thái: từ chối/)).toBeTruthy();
    });
    expect(screen.queryByText(/rejected/)).toBeNull();
    view.unmount();
    view.queryClient.clear();
  });

  it('renders clean Vietnamese staff header without MLOps jargon', async () => {
    mockSessionState.user = { id: 'adm-1', email: 'admin@tastoria.vn', role: 'admin', onboarding_completed: true };
    await renderWithProviders(<Settings />);
    expect(await screen.findByText('Bảng quản trị & vận hành mô hình')).toBeTruthy();
    expect(screen.queryByText(/MLOps/)).toBeNull();
  });

  it('checks query error BEFORE !draft across Profile, Allergen, Favs, and Kitchen sections', async () => {
    mockedGet.mockImplementation(async () => errRes(500, { code: 'internal_error' }));

    const view = await renderWithProviders(<Settings />);

    for (const groupTestId of ['settings-profile', 'settings-allergen', 'settings-favs', 'settings-kitchen']) {
      await fireEvent.press(screen.getByTestId(groupTestId));
      await waitFor(() => {
        expect(screen.getAllByText('Thử lại').length).toBeGreaterThanOrEqual(1);
      });
    }
    view.unmount();
    view.queryClient.clear();
  });

  it('stops DSR polling when status is rejected', async () => {
    jest.useFakeTimers();
    let pollCount = 0;
    mockedPost.mockResolvedValueOnce(okRes({ id: 'exp-rej' }));
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/me/data-requests/{id}') {
        pollCount += 1;
        return okRes({ id: 'exp-rej', status: 'rejected', due_at: '2026-11-25T10:00:00Z', download_available: false });
      }
      return okRes({});
    });

    const view = await renderWithProviders(<Settings />);
    try {
      await fireEvent.press(screen.getByTestId('settings-export'));
      await fireEvent.press(await screen.findByText('Gửi yêu cầu tải dữ liệu'));
      await waitFor(() => expect(screen.getByText(/Trạng thái: từ chối/)).toBeTruthy());

      const countAtRejected = pollCount;
      await act(async () => {
        jest.advanceTimersByTime(10_000);
      });
      expect(pollCount).toBe(countAtRejected);
    } finally {
      view.unmount();
      view.queryClient.clear();
      jest.useRealTimers();
    }
  });

  it('appends export anchor to document.body as my-vi-du-lieu.zip and defers revokeObjectURL by 10s on web', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'web', configurable: true });
    mockedPost.mockResolvedValueOnce(okRes({ id: 'exp-zip' }));
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/me/data-requests/{id}') {
        return okRes({ id: 'exp-zip', status: 'completed', due_at: '2026-11-25T10:00:00Z', download_available: true });
      }
      if (path === '/me/data-requests/{id}/download') {
        return okRes(new Blob(['zip-bytes'], { type: 'application/zip' }));
      }
      return okRes({});
    });

    const view2 = await renderWithProviders(<Settings />);
    await fireEvent.press(screen.getByTestId('settings-export'));
    await fireEvent.press(await screen.findByText('Gửi yêu cầu tải dữ liệu'));
    const dlBtn = await screen.findByText('Tải tệp (.zip)');

    const anchorMock = {
      href: '',
      download: '',
      style: { display: '' },
      click: jest.fn(),
      remove: jest.fn(),
    };
    const hasOwnDoc = Object.prototype.hasOwnProperty.call(globalThis, 'document');
    const origDoc = (globalThis as unknown as { document?: unknown }).document;
    const origCreateUrl = globalThis.URL.createObjectURL;
    const origRevokeUrl = globalThis.URL.revokeObjectURL;
    const origSetTimeout = globalThis.setTimeout;

    const appendChild = jest.fn();
    const createElement = jest.fn(() => anchorMock);
    const createObjectURL = jest.fn(() => 'blob:zip-export-url');
    const revokeObjectURL = jest.fn();
    const timerHandles: ReturnType<typeof setTimeout>[] = [];
    const scheduled: { fn: () => void; ms?: number }[] = [];

    Object.defineProperty(globalThis, 'document', {
      value: { createElement, body: { appendChild } },
      configurable: true,
    });
    globalThis.URL.createObjectURL = createObjectURL;
    globalThis.URL.revokeObjectURL = revokeObjectURL;
    globalThis.setTimeout = ((fn: () => void, ms?: number, ...rest: unknown[]) => {
      scheduled.push({ fn, ms });
      const handle = origSetTimeout(fn, ms, ...(rest as []));
      timerHandles.push(handle);
      return handle;
    }) as unknown as typeof setTimeout;

    try {
      await fireEvent.press(dlBtn);
      await waitFor(() => expect(anchorMock.click).toHaveBeenCalledTimes(1));
      expect(appendChild).toHaveBeenCalledWith(anchorMock);
      expect(anchorMock.download).toBe('my-vi-du-lieu.zip');
      expect(anchorMock.remove).toHaveBeenCalledTimes(1);
      expect(revokeObjectURL).not.toHaveBeenCalled();

      const revokeEntry = scheduled.find((s) => s.ms === 10_000);
      expect(revokeEntry).toBeDefined();
      revokeEntry!.fn();
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:zip-export-url');
    } finally {
      globalThis.setTimeout = origSetTimeout;
      timerHandles.forEach((h) => clearTimeout(h));
      if (hasOwnDoc) {
        Object.defineProperty(globalThis, 'document', { value: origDoc, configurable: true });
      } else {
        delete (globalThis as unknown as { document?: unknown }).document;
      }
      globalThis.URL.createObjectURL = origCreateUrl;
      globalThis.URL.revokeObjectURL = origRevokeUrl;
      view2.unmount();
      view2.queryClient.clear();
    }
  });

  it('disables PolicyCard switches while consent mutation is pending', async () => {
    let resolvePost!: () => void;
    mockedGet.mockImplementation(async (path: string, opts?: { params?: { path?: { purpose?: string } } }) => {
      if (path === '/me/consents') return okRes({ items: [] });
      if (path === '/policies/{purpose}/current') {
        const purposeCode = opts?.params?.path?.purpose ?? 'personalization';
        return okRes({
          id: `pol-${purposeCode}`,
          purpose_code: purposeCode,
          version: 1,
          title_vi: `Chính sách ${purposeCode}`,
          text_vi: 'Toàn văn điều khoản.',
          purpose: {
            code: purposeCode,
            name_vi: `Mục ${purposeCode}`,
            description_vi: 'Mô tả ngắn gọn',
            data_category: 'Hồ sơ',
            is_sensitive: false,
          },
        });
      }
      return okRes({});
    });
    mockedPost.mockImplementationOnce(
      () =>
        new Promise((res) => {
          resolvePost = () => res(okRes({}));
        }),
    );

    const view = await renderWithProviders(<Settings />);
    await fireEvent.press(screen.getByTestId('settings-consent'));
    const checkbox = await screen.findByTestId('consent-personalization');
    expect(checkbox.props.accessibilityState?.disabled).toBeFalsy();

    await fireEvent.press(checkbox);
    await waitFor(() => {
      expect(screen.getByTestId('consent-personalization').props.accessibilityState?.disabled).toBe(true);
    });
    resolvePost();
    await waitFor(() => {
      expect(screen.getByTestId('consent-personalization').props.accessibilityState?.disabled).toBeFalsy();
    });
    view.unmount();
    view.queryClient.clear();
  });

  it('renders Verify Email, Change Password, and Sessions management sections', async () => {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/auth/sessions') {
        return okRes({
          items: [
            { id: 's-cur', client_platform: 'web', created_at: '2026-11-24T08:00:00Z', last_used_at: '2026-11-24T09:00:00Z', is_current: true },
            { id: 's-old', client_platform: 'android', created_at: '2026-11-20T08:00:00Z', last_used_at: '2026-11-21T09:00:00Z', is_current: false },
          ],
        });
      }
      return okRes({});
    });
    mockedPost.mockResolvedValue(
      okRes({
        access_token: 'acc-new',
        refresh_token: null,
        token_type: 'bearer',
        expires_in: 900,
        user: { id: 'user-1', email: 'cook@example.vn', role: 'user', onboarding_completed: true },
      }),
    );
    mockedDelete.mockResolvedValueOnce(okRes(undefined));

    const view = await renderWithProviders(<Settings />);

    // Verify Email section
    await fireEvent.press(screen.getByTestId('settings-verify-email'));
    expect(await screen.findByTestId('settings-verify-email-section')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('verify-email-resend'));
    await waitFor(() => expect(mockedPost).toHaveBeenCalledWith('/auth/verify-email/request'));

    // Change Password section
    await fireEvent.press(screen.getByTestId('settings-password'));
    expect(await screen.findByTestId('settings-change-password-section')).toBeTruthy();
    await fireEvent.changeText(screen.getByTestId('cp-current'), 'OldPassw0rd!');
    await fireEvent.changeText(screen.getByTestId('cp-new'), 'NewStrongPass99!');
    await fireEvent.changeText(screen.getByTestId('cp-confirm'), 'NewStrongPass99!');
    await fireEvent.press(screen.getByTestId('cp-submit'));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith('/auth/change-password', {
        body: { current_password: 'OldPassw0rd!', new_password: 'NewStrongPass99!' },
      }),
    );

    // Sessions section
    await fireEvent.press(screen.getByTestId('settings-sessions'));
    expect(await screen.findByTestId('session-row-s-cur')).toBeTruthy();
    expect(screen.getByTestId('session-row-s-old')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('session-revoke-s-old'));
    await waitFor(() =>
      expect(mockedDelete).toHaveBeenCalledWith('/auth/sessions/{session_id}', { params: { path: { session_id: 's-old' } } }),
    );
    view.unmount();
    view.queryClient.clear();
  });
});
