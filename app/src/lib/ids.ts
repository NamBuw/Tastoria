import * as Crypto from 'expo-crypto';

/** UUID v4 for Idempotency-Key and event_id. */
export function uuid(): string {
  return Crypto.randomUUID();
}
