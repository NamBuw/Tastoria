/**
 * Web: no secure store. The refresh token lives in sessionStorage (gone when the tab closes) with an
 * in-memory fallback when storage is blocked; the access token stays in memory only.
 */
const KEY = 'tastoria.refresh';
let memory: string | null = null;

export async function loadRefresh(): Promise<string | null> {
  try {
    return window.sessionStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

export async function saveRefresh(token: string | null): Promise<void> {
  memory = token;
  try {
    if (token) window.sessionStorage.setItem(KEY, token);
    else window.sessionStorage.removeItem(KEY);
  } catch {
    // storage blocked: memory only
  }
}
