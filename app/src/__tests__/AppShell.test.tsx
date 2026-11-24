import { fireEvent, screen } from '@testing-library/react-native';
import React from 'react';
import { Text } from 'react-native';

import { AppShell } from '@/components/AppShell';

import { mockNavState, mockRouter, mockSessionState } from '../../jest.setup';
import { renderWithProviders, setWindowWidth } from './test-utils';

describe('AppShell', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders desktop-sidebar-rail at >=1024px and masks email', async () => {
    setWindowWidth(1280, 900);
    mockSessionState.status = 'signedIn';
    mockSessionState.user = {
      id: 'u1',
      email: 'minhanh@tastoria.vn',
      role: 'user',
      onboarding_completed: true,
    };

    await renderWithProviders(
      <AppShell>
        <Text testID="child-content">Nội dung chính</Text>
      </AppShell>,
    );

    expect(screen.getByTestId('desktop-sidebar-rail')).toBeTruthy();
    expect(screen.queryByTestId('tablet-rail')).toBeNull();
    expect(screen.getByTestId('sidebar-nav-bep')).toBeTruthy();
    expect(screen.getByTestId('sidebar-nav-quet')).toBeTruthy();
    expect(screen.getByTestId('sidebar-nav-mam')).toBeTruthy();
    expect(screen.getByTestId('sidebar-nav-kho')).toBeTruthy();
    expect(screen.getByTestId('sidebar-nav-nhat-ky')).toBeTruthy();
    expect(screen.getByTestId('sidebar-nav-di-cho')).toBeTruthy();
    expect(screen.getByTestId('sidebar-nav-cai-dat')).toBeTruthy();
    expect(screen.queryByTestId('sidebar-nav-kham-pha')).toBeNull();
    expect(screen.queryByTestId('theme-toggle')).toBeNull();
    expect(screen.getByText('mi***@tastoria.vn')).toBeTruthy();
    expect(screen.getByTestId('child-content')).toBeTruthy();
  });

  it('renders tablet-rail at 768-1023px', async () => {
    setWindowWidth(800, 1024);
    mockSessionState.status = 'signedIn';

    await renderWithProviders(
      <AppShell>
        <Text testID="child-content">Tablet</Text>
      </AppShell>,
    );

    expect(screen.getByTestId('tablet-rail')).toBeTruthy();
    expect(screen.queryByTestId('desktop-sidebar-rail')).toBeNull();
    expect(screen.queryByTestId('theme-toggle')).toBeNull();
    expect(screen.getByTestId('sidebar-nav-bep')).toBeTruthy();
  });

  it('suppresses sidebar and tablet rail on mobile (<768px)', async () => {
    setWindowWidth(390, 844);
    mockSessionState.status = 'signedIn';

    await renderWithProviders(
      <AppShell>
        <Text testID="child-content">Mobile</Text>
      </AppShell>,
    );

    expect(screen.queryByTestId('desktop-sidebar-rail')).toBeNull();
    expect(screen.queryByTestId('tablet-rail')).toBeNull();
    expect(screen.getByTestId('child-content')).toBeTruthy();
  });

  it.each([
    ['auth dang-nhap', ['(auth)', 'dang-nhap'], 'signedIn'],
    ['auth dang-ky', ['(auth)', 'dang-ky'], 'signedIn'],
    ['onboarding', ['onboarding', 'index'], 'signedIn'],
    ['dat-lai-mat-khau', ['dat-lai-mat-khau'], 'signedIn'],
    ['signed-out khao-sat', ['khao-sat'], 'signedOut'],
    ['signed-out bep', ['(tabs)', 'bep'], 'signedOut'],
  ] as const)('suppresses rail on %s even at desktop width', async (_label, segments, status) => {
    setWindowWidth(1440, 900);
    mockNavState.segments = [...segments];
    mockSessionState.status = status;
    if (status === 'signedOut') mockSessionState.user = null;

    await renderWithProviders(
      <AppShell>
        <Text testID="child-content">Suppressed</Text>
      </AppShell>,
    );

    expect(screen.queryByTestId('desktop-sidebar-rail')).toBeNull();
    expect(screen.queryByTestId('tablet-rail')).toBeNull();
    expect(screen.getByTestId('child-content')).toBeTruthy();
  });

  it('keeps rail visible on khao-sat when signedIn at desktop width', async () => {
    setWindowWidth(1280, 900);
    mockNavState.segments = ['khao-sat'];
    mockSessionState.status = 'signedIn';

    await renderWithProviders(
      <AppShell>
        <Text>Survey</Text>
      </AppShell>,
    );

    expect(screen.getByTestId('desktop-sidebar-rail')).toBeTruthy();
  });

  it('shows sidebar-nav-quan-tri only for admin and ml_operator, never user or curator', async () => {
    setWindowWidth(1280, 900);

    for (const role of ['user', 'curator'] as const) {
      mockSessionState.user = { id: 'u1', email: 'a@b.vn', role, onboarding_completed: true };
      const { unmount } = await renderWithProviders(
        <AppShell>
          <Text>Body</Text>
        </AppShell>,
      );
      expect(screen.queryByTestId('sidebar-nav-quan-tri')).toBeNull();
      await unmount();
    }

    for (const role of ['admin', 'ml_operator'] as const) {
      mockSessionState.user = { id: 'u2', email: 'staff@b.vn', role, onboarding_completed: true };
      const { unmount } = await renderWithProviders(
        <AppShell>
          <Text>Body</Text>
        </AppShell>,
      );
      const navAdmin = screen.getByTestId('sidebar-nav-quan-tri');
      expect(navAdmin).toBeTruthy();
      await fireEvent.press(navAdmin);
      expect(mockRouter.push).toHaveBeenCalledWith('/quan-tri');
      await unmount();
    }
  });
});
