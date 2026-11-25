import type * as WinterFormData from 'expo/build/winter/FormData';
import { convertFormDataAsync } from 'expo/build/winter/fetch/convertFormData';
import { Platform } from 'react-native';

import {
  decodeBase64ToUint8Array,
  imagePart,
  prepareImage,
  type NativeFormDataFile,
} from '@/lib/image';

const { installFormDataPatch } = jest.requireActual<typeof WinterFormData>('expo/build/winter/FormData');

class MockRNFormData {
  _parts: [string, unknown][] = [];
  append(key: string, value: unknown) {
    this._parts.push([key, value]);
  }
}

describe('Native Android FormData image upload and API fallback', () => {
  const originalPlatform = Platform.OS;
  const originalFetch = globalThis.fetch;
  const originalApiUrl = process.env.EXPO_PUBLIC_API_URL;

  beforeEach(() => {
    Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    Object.defineProperty(Platform, 'OS', { value: originalPlatform, configurable: true });
    if (originalApiUrl === undefined) {
      delete process.env.EXPO_PUBLIC_API_URL;
    } else {
      process.env.EXPO_PUBLIC_API_URL = originalApiUrl;
    }
    jest.restoreAllMocks();
  });

  it('produces an Expo-fetch bytes() part that convertFormDataAsync serializes cleanly', async () => {
    const sampleJpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]);
    globalThis.fetch = jest.fn(async () => ({
      ok: true,
      bytes: async () => sampleJpeg,
      arrayBuffer: async () => sampleJpeg.buffer,
    })) as unknown as typeof fetch;

    const part = (await imagePart(
      { uri: 'file:///data/user/0/net.ctslab.tastoria/cache/meal.jpg', width: 800, height: 600 },
      'mon-an.jpg',
    )) as NativeFormDataFile;

    expect(part.name).toBe('mon-an.jpg');
    expect(part.type).toBe('image/jpeg');
    expect(part.uri).toContain('meal.jpg');
    expect(Array.from(await part.bytes())).toEqual(Array.from(sampleJpeg));
    // Re-reading bytes for 401 refresh retry must stay idempotent.
    expect(Array.from(await part.bytes())).toEqual(Array.from(sampleJpeg));

    const ExpoFormData = installFormDataPatch(MockRNFormData as unknown as typeof FormData);
    const fd = new ExpoFormData();
    fd.append('portion', 'vua');
    fd.append('image', part as unknown as Blob, 'mon-an.jpg');

    const { body, boundary } = await convertFormDataAsync(
      fd as unknown as FormData,
      '----ExpoFetchFormBoundaryTest00000000',
    );
    const serialized = new TextDecoder().decode(body);
    expect(boundary).toBe('----ExpoFetchFormBoundaryTest00000000');
    expect(serialized).toContain('content-disposition: form-data; name="image"; filename="mon-an.jpg"');
    expect(serialized).toContain('content-type: image/jpeg');

    // Confirm legacy {uri, name, type} without bytes() would still fail under Expo 58 fetch.
    const legacyFd = new ExpoFormData();
    legacyFd.append('image', { uri: 'file:///cache/legacy.jpg', name: 'legacy.jpg', type: 'image/jpeg' });
    await expect(convertFormDataAsync(legacyFd as unknown as FormData)).rejects.toThrow(
      /Unsupported FormDataPart implementation/,
    );
  });

  it('requests base64 on native prepareImage and falls back to base64 if file:// fetch fails', async () => {
    const prepared = await prepareImage('content://media/external/images/media/42');
    expect(prepared.base64).toBe('/9j/4AAQ');

    globalThis.fetch = jest.fn(async () => {
      throw new TypeError('Local file fetch failed');
    }) as unknown as typeof fetch;

    const part = (await imagePart(prepared, 'anh-1.jpg')) as NativeFormDataFile;
    expect(Array.from(await part.bytes())).toEqual([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]);
  });

  it('decodes base64 strings cleanly across padding variants', () => {
    expect(Array.from(decodeBase64ToUint8Array(''))).toEqual([]);
    expect(Array.from(decodeBase64ToUint8Array('QQ=='))).toEqual([65]);
    expect(Array.from(decodeBase64ToUint8Array('QUI='))).toEqual([65, 66]);
    expect(new TextDecoder().decode(decodeBase64ToUint8Array('SGVsbG8='))).toBe('Hello');
  });

  it('defaults API_URL to https://tastoria.ctslab.net/api/v1 on native when EXPO_PUBLIC_API_URL is unset', () => {
    delete process.env.EXPO_PUBLIC_API_URL;
    Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
    jest.isolateModules(() => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const client = require('@/api/client') as typeof import('@/api/client');
      expect(client.API_URL).toBe('https://tastoria.ctslab.net/api/v1');
    });
  });
});
