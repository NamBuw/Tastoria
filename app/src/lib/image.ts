import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import { Platform } from 'react-native';

const LONG_EDGE = 1280;

export type PreparedImage = { uri: string; width: number; height: number };

/** Resize so the long edge is at most 1280 px and re-encode as JPEG (spec v2 §9; server limit 3 MB). */
export async function prepareImage(uri: string): Promise<PreparedImage> {
  const ctx = ImageManipulator.manipulate(uri);
  const probe = await ctx.renderAsync();
  const long = Math.max(probe.width, probe.height);
  let ref = probe;
  if (long > LONG_EDGE) {
    const resize = probe.width >= probe.height ? { width: LONG_EDGE } : { height: LONG_EDGE };
    ref = await ImageManipulator.manipulate(uri).resize(resize).renderAsync();
  }
  const out = await ref.saveAsync({ format: SaveFormat.JPEG, compress: 0.82 });
  return { uri: out.uri, width: out.width, height: out.height };
}

/** Form-data part for one JPEG: a Blob on web, a {uri,name,type} file descriptor on Android. */
export async function imagePart(img: PreparedImage, name: string): Promise<Blob | { uri: string; name: string; type: string }> {
  if (Platform.OS === 'web') {
    const res = await fetch(img.uri);
    return await res.blob();
  }
  return { uri: img.uri, name, type: 'image/jpeg' };
}
