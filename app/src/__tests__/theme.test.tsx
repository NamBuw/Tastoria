import { render, screen, waitFor } from '@testing-library/react-native';
import React from 'react';
import { Text, View } from 'react-native';
import * as RN from 'react-native';

import { light, ThemeProvider, useTheme } from '@/theme';

function ThemeProbe() {
  const { c, scheme } = useTheme();
  return (
    <View>
      <Text testID="scheme">{scheme}</Text>
      <Text testID="bg">{c.bg}</Text>
      <Text testID="border">{c.border}</Text>
      <Text testID="borderDashed">{c.borderDashed}</Text>
    </View>
  );
}

describe('tokens & Light-only ThemeProvider', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('exposes the Light "Sổ Bếp Mỹ Vị" antique honey-parchment palette tokens', () => {
    expect(light.bg).toBe('#E3CFA6');
    expect(light.surface).toBe('#FAF2E0');
    expect(light.surfaceCard).toBe('rgba(250, 242, 224, 0.84)');
    expect(light.surfaceAlt).toBe('#EADAB8');
    expect(light.text).toBe('#19120B');
    expect(light.muted).toBe('#4E3E2F');
    expect(light.accent).toBe('#9E2F1E');
    expect(light.accentDisplay).toBe('#7F2315');
    expect(light.herb).toBe('#2E4F33');
    expect(light.border).toBe('#5A432B');
    expect(light.borderDashed).toBe('#6E5438');
    expect(light.hairline).toBe('#BFA982');
    expect(light.warn).toBe('#734609');
    expect(light.info).toBe('#32424A');
    expect(light.editorialSurface).toBe('#1A1510');
    expect(light.trayRim).toBe('#D8B979');
    expect(Object.keys(light.macroChart).sort()).toEqual(['carb', 'fiber', 'lipid', 'protein']);
    expect(light.macroChart).toEqual({
      carb: '#B97A20',
      protein: '#9E2F1E',
      lipid: '#2E4F33',
      fiber: '#5F7D57',
    });
  });

  it('uses Light newsprint when OS preference is light', async () => {
    jest.spyOn(RN, 'useColorScheme').mockReturnValue('light');
    await render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('scheme').props.children).toBe('light');
    });
    expect(screen.getByTestId('bg').props.children).toBe(light.bg);
    expect(screen.getByTestId('border').props.children).toBe('#5A432B');
    expect(screen.getByTestId('borderDashed').props.children).toBe('#6E5438');
  });

  it('stays locked to Light newsprint even when OS useColorScheme() returns dark', async () => {
    jest.spyOn(RN, 'useColorScheme').mockReturnValue('dark');
    await render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('scheme').props.children).toBe('light');
    });
    expect(screen.getByTestId('bg').props.children).toBe('#E3CFA6');
  });

  it('sets Be Vietnam Pro body fontFamily and light colorScheme on web', async () => {
    const origPlatform = RN.Platform.OS;
    const origDocument = (globalThis as unknown as { document?: unknown }).document;
    const metaEl = { name: '', content: '' };
    const appended: unknown[] = [];
    const fakeDoc = {
      documentElement: { dataset: {} as Record<string, string>, style: { colorScheme: '' } },
      body: { style: { backgroundColor: '', fontFamily: '' } },
      head: { appendChild: (el: unknown) => appended.push(el) },
      querySelector: () => null,
      createElement: () => metaEl,
    };
    Object.defineProperty(RN.Platform, 'OS', { value: 'web', configurable: true });
    Object.defineProperty(globalThis, 'document', { value: fakeDoc, configurable: true });
    try {
      await render(
        <ThemeProvider>
          <ThemeProbe />
        </ThemeProvider>,
      );
      await waitFor(() => {
        expect(fakeDoc.body.style.fontFamily).toBe('BeVietnamPro_400Regular, "Be Vietnam Pro", system-ui, sans-serif');
      });
      expect(fakeDoc.body.style.backgroundColor).toBe(light.bg);
      expect(fakeDoc.documentElement.style.colorScheme).toBe('light');
      expect(fakeDoc.documentElement.dataset.theme).toBe('light');
      expect(metaEl.content).toBe(light.bg);
      expect(appended).toHaveLength(1);
    } finally {
      Object.defineProperty(RN.Platform, 'OS', { value: origPlatform, configurable: true });
      Object.defineProperty(globalThis, 'document', { value: origDocument, configurable: true });
    }
  });
});
