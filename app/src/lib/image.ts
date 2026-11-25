import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import { Platform } from 'react-native';

const LONG_EDGE = 1280;
const BASE64_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const BASE64_LOOKUP = (() => {
  const table = new Int16Array(128).fill(-1);
  for (let i = 0; i < BASE64_ALPHABET.length; i += 1) {
    table[BASE64_ALPHABET.charCodeAt(i)] = i;
  }
  return table;
})();

export type PreparedImage = { uri: string; width: number; height: number; base64?: string };
export type NativeFormDataFile = {
  uri: string;
  name: string;
  type: string;
  bytes: () => Promise<Uint8Array>;
};

function releaseSharedObject(obj: unknown): void {
  if (obj && typeof (obj as { release?: unknown }).release === 'function') {
    try {
      (obj as { release: () => void }).release();
    } catch {
      // ignore cleanup errors on already-released native handles
    }
  }
}

/** Decodes standard base64 text to bytes without relying on Node Buffer or DOM atob. */
export function decodeBase64ToUint8Array(b64: string): Uint8Array {
  const clean = b64.replace(/\s+/g, '').replace(/=+$/, '');
  if (!clean) return new Uint8Array(0);
  const byteLen = Math.floor((clean.length * 3) / 4);
  const out = new Uint8Array(byteLen);
  let outIdx = 0;
  for (let i = 0; i < clean.length; i += 4) {
    const c1 = BASE64_LOOKUP[clean.charCodeAt(i)] ?? -1;
    const c2 = BASE64_LOOKUP[clean.charCodeAt(i + 1)] ?? -1;
    const has3 = i + 2 < clean.length;
    const has4 = i + 3 < clean.length;
    const c3 = has3 ? (BASE64_LOOKUP[clean.charCodeAt(i + 2)] ?? -1) : 0;
    const c4 = has4 ? (BASE64_LOOKUP[clean.charCodeAt(i + 3)] ?? -1) : 0;
    if (c1 < 0 || c2 < 0 || (has3 && c3 < 0) || (has4 && c4 < 0)) {
      throw new Error('Invalid base64 image payload');
    }
    const n = (c1 << 18) | (c2 << 12) | (c3 << 6) | c4;
    if (outIdx < byteLen) out[outIdx++] = (n >> 16) & 0xff;
    if (has3 && outIdx < byteLen) out[outIdx++] = (n >> 8) & 0xff;
    if (has4 && outIdx < byteLen) out[outIdx++] = n & 0xff;
  }
  return out.subarray(0, outIdx);
}

/** Reads local prepared JPEG bytes via Expo's file:// fetch interceptor with base64 fallback. */
async function loadNativeImageBytes(img: PreparedImage): Promise<Uint8Array> {
  let fetchError: unknown = null;
  if (typeof fetch === 'function') {
    try {
      const res = await fetch(img.uri);
      if (res.ok) {
        const resWithBytes = res as Response & { bytes?: () => Promise<Uint8Array> };
        const data =
          typeof resWithBytes.bytes === 'function'
            ? await resWithBytes.bytes()
            : new Uint8Array(await res.arrayBuffer());
        if (data.byteLength > 0) return data;
        fetchError = new Error('Empty image payload from URI');
      } else {
        fetchError = new Error(`Failed to read prepared image (${res.status})`);
      }
    } catch (e) {
      fetchError = e;
    }
  }
  if (img.base64) {
    const decoded = decodeBase64ToUint8Array(img.base64);
    if (decoded.byteLength > 0) return decoded;
  }
  throw fetchError instanceof Error ? fetchError : new Error('Unable to read prepared image bytes');
}

/** Resize so the long edge is at most 1280 px and re-encode as JPEG (spec v2 §9; server limit 3 MB). */
export async function prepareImage(uri: string): Promise<PreparedImage> {
  const ctx = ImageManipulator.manipulate(uri);
  let probe: Awaited<ReturnType<typeof ctx.renderAsync>> | null = null;
  let resizeCtx: ReturnType<typeof ImageManipulator.manipulate> | null = null;
  let ref: Awaited<ReturnType<typeof ctx.renderAsync>> | null = null;
  try {
    probe = await ctx.renderAsync();
    const long = Math.max(probe.width, probe.height);
    ref = probe;
    if (long > LONG_EDGE) {
      const resize = probe.width >= probe.height ? { width: LONG_EDGE } : { height: LONG_EDGE };
      resizeCtx = ImageManipulator.manipulate(uri).resize(resize);
      ref = await resizeCtx.renderAsync();
    }
    const out = await ref.saveAsync({
      format: SaveFormat.JPEG,
      compress: 0.82,
      ...(Platform.OS !== 'web' ? { base64: true } : {}),
    });
    return {
      uri: out.uri,
      width: out.width,
      height: out.height,
      ...(out.base64 ? { base64: out.base64 } : {}),
    };
  } finally {
    if (ref && ref !== probe) releaseSharedObject(ref);
    if (resizeCtx) releaseSharedObject(resizeCtx);
    if (probe) releaseSharedObject(probe);
    releaseSharedObject(ctx);
  }
}

/** Form-data part for one JPEG: a Blob on web, or an Expo-fetch compatible bytes() file part on native. */
export async function imagePart(img: PreparedImage, name: string): Promise<Blob | NativeFormDataFile> {
  if (Platform.OS === 'web') {
    const res = await fetch(img.uri);
    return await res.blob();
  }
  const data = await loadNativeImageBytes(img);
  return {
    uri: img.uri,
    name,
    type: 'image/jpeg',
    bytes: async () => data,
  };
}
