import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderOptions } from '@testing-library/react-native';
import React, { type ReactElement } from 'react';
import * as RN from 'react-native';

import { ThemeProvider } from '@/theme';

const activeQueryClients = new Set<QueryClient>();

afterEach(() => {
  activeQueryClients.forEach((qc) => qc.clear());
  activeQueryClients.clear();
});

export function makeQueryClient() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
      },
      mutations: {
        retry: false,
        gcTime: Infinity,
      },
    },
  });
  activeQueryClients.add(qc);
  return qc;
}

export async function renderWithProviders(
  ui: ReactElement,
  options?: RenderOptions & { queryClient?: QueryClient },
) {
  const qc = options?.queryClient ?? makeQueryClient();
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <ThemeProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </ThemeProvider>
  );
  const res = await render(ui, { wrapper: Wrapper, ...options });
  return {
    queryClient: qc,
    ...res,
  };
}

export function okRes<T>(data: T, status = 200) {
  return {
    data,
    error: undefined,
    response: { ok: true, status } as Response,
  };
}

export function errRes(
  status: number,
  error: { code: string; detail?: string; [k: string]: unknown } = { code: 'bad_request' },
) {
  return {
    data: undefined,
    error,
    response: { ok: false, status } as Response,
  };
}

export function setWindowWidth(width: number, height = 900) {
  RN.Dimensions.set({
    window: { width, height, scale: 1, fontScale: 1 },
    screen: { width, height, scale: 1, fontScale: 1 },
  });
}
