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

  it('exposes the clean high-contrast warm-kitchen light palette tokens', () => {
    expect(light.bg).toBe('#FAF8F5');
    expect(light.surface).toBe('#FFFFFF');
    expect(light.surfaceCard).toBe('#FFFFFF');
    expect(light.surfaceAlt).toBe('#F3EFE9');
    expect(light.text).toBe('#1C1917');
    expect(light.muted).toBe('#57534E');
    expect(light.accent).toBe('#B53827');
    expect(light.accentDisplay).toBe('#8F291B');
    expect(light.herb).toBe('#23633A');
    expect(light.border).toBe('#8A8178');
    expect(light.borderDashed).toBe('#9B9289');
    expect(light.hairline).toBe('#E7E2DA');
    expect(light.warn).toBe('#92400E');
    expect(light.info).toBe('#1D4ED8');
    expect(light.editorialSurface).toBe('#1C1917');
    expect(light.trayRim).toBe('#D6CFC7');
    expect(Object.keys(light.macroChart).sort()).toEqual(['carb', 'fiber', 'lipid', 'protein']);
    expect(light.macroChart).toEqual({
      carb: '#D97706',
      protein: '#B53827',
      lipid: '#23633A',
      fiber: '#3D6B0B',
    });
  });

  it('uses crisp warm-kitchen canvas when OS preference is light', async () => {
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
    expect(screen.getByTestId('border').props.children).toBe('#8A8178');
    expect(screen.getByTestId('borderDashed').props.children).toBe('#9B9289');
  });

  it('stays locked to Light theme even when OS useColorScheme() returns dark', async () => {
    jest.spyOn(RN, 'useColorScheme').mockReturnValue('dark');
    await render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('scheme').props.children).toBe('light');
    });
    expect(screen.getByTestId('bg').props.children).toBe('#FAF8F5');
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
