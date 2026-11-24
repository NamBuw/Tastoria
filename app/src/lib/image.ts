import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import { Platform } from 'react-native';

const LONG_EDGE = 1280;

export type PreparedImage = { uri: string; width: number; height: number };

function releaseSharedObject(obj: unknown): void {
  if (obj && typeof (obj as { release?: unknown }).release === 'function') {
    try {
      (obj as { release: () => void }).release();
    } catch {
      // ignore cleanup errors on already-released native handles
    }
  }
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
    const out = await ref.saveAsync({ format: SaveFormat.JPEG, compress: 0.82 });
    return { uri: out.uri, width: out.width, height: out.height };
  } finally {
    if (ref && ref !== probe) releaseSharedObject(ref);
    if (resizeCtx) releaseSharedObject(resizeCtx);
    if (probe) releaseSharedObject(probe);
    releaseSharedObject(ctx);
  }
}

/** Form-data part for one JPEG: a Blob on web, a {uri,name,type} file descriptor on Android. */
export async function imagePart(img: PreparedImage, name: string): Promise<Blob | { uri: string; name: string; type: string }> {
  if (Platform.OS === 'web') {
    const res = await fetch(img.uri);
    return await res.blob();
  }
  return { uri: img.uri, name, type: 'image/jpeg' };
}
