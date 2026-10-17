import { useRef } from 'react';

import { uuid } from './ids';

/**
 * One Idempotency-Key per request body: retries of the same body reuse the key (server replays the stored
 * response), a different body gets a new key (otherwise 422 idempotency_key_reused).
 */
export function useIdempotencyKey() {
  const ref = useRef<{ sig: string; key: string } | null>(null);
  return {
    keyFor(body: unknown): string {
      const sig = JSON.stringify(body);
      if (!ref.current || ref.current.sig !== sig) ref.current = { sig, key: uuid() };
      return ref.current.key;
    },
    reset() {
      ref.current = null;
    },
  };
}
