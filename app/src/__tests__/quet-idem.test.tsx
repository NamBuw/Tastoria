import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import * as ImagePicker from 'expo-image-picker';
import React from 'react';

import { api } from '@/api/client';
import Scan from '@/app/quet/index';

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

describe('Scan Idempotency-Key reset behavior', () => {
  beforeEach(() => {
    setWindowWidth(1280, 900);
    mockedGet.mockReset();
    mockedPost.mockReset();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('keeps Idempotency-Key on 409 idempotency_in_progress and resets on terminal 422', async () => {
    mockedGet.mockImplementation(async (path: string) => {
      if (path === '/me/consents') return okRes({ items: [] });
      return okRes({});
    });

    (ImagePicker.launchImageLibraryAsync as jest.Mock).mockResolvedValueOnce({
      canceled: false,
      assets: [{ uri: 'file:///tmp/fridge.jpg' }],
    });

    mockedPost
      .mockResolvedValueOnce(errRes(409, { code: 'idempotency_in_progress' }))
      .mockResolvedValueOnce(errRes(422, { code: 'validation_error' }))
      .mockResolvedValueOnce(okRes({ id: 'scan-created' }));

    await renderWithProviders(<Scan />);

    await fireEvent.press(screen.getByTestId('scan-library'));
    await waitFor(() => {
      expect(screen.getByLabelText('Ảnh 1')).toBeTruthy();
    });

    // 1st attempt -> 409 idempotency_in_progress (key must NOT be reset)
    await fireEvent.press(screen.getByTestId('scan-send'));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledTimes(1);
    });

    // 2nd attempt -> same key, receives terminal 422 (key MUST be reset)
    await fireEvent.press(screen.getByTestId('scan-send'));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledTimes(2);
    });

    // 3rd attempt -> fresh key, succeeds
    await fireEvent.press(screen.getByTestId('scan-send'));
    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledTimes(3);
    });

    const key1 = mockedPost.mock.calls[0][1].params.header['Idempotency-Key'];
    const key2 = mockedPost.mock.calls[1][1].params.header['Idempotency-Key'];
    const key3 = mockedPost.mock.calls[2][1].params.header['Idempotency-Key'];

    expect(key1).toBeTruthy();
    expect(key2).toBe(key1);
    expect(key3).not.toBe(key1);
  });
});
