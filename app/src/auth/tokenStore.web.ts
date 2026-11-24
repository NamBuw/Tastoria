/**
 * Web: refresh token is managed exclusively via HttpOnly cookie (`tastoria_refresh`)
 * by the backend when `X-Client-Platform: web` is sent. Never persist refresh tokens in
 * browser web storage; the access token stays in memory only.
 */
export async function loadRefresh(): Promise<string | null> {
  return null;
}

export async function saveRefresh(_token: string | null): Promise<void> {
  // No-op on web: HttpOnly cookie lifecycle is owned by the server.
}
