import * as SecureStore from 'expo-secure-store';

/** Android: refresh token in the Keystore-backed secure store; access token only in memory. */
const KEY = 'tastoria.refresh';

export async function loadRefresh(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(KEY);
  } catch {
    return null;
  }
}

export async function saveRefresh(token: string | null): Promise<void> {
  if (token) await SecureStore.setItemAsync(KEY, token);
  else await SecureStore.deleteItemAsync(KEY);
}
