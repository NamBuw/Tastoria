import { useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Platform } from 'react-native';

import {
  api,
  bumpSessionEpoch,
  call,
  currentRefreshToken,
  ensureAuthChannel,
  getCurrentUserId,
  onSessionChange,
  refreshSession,
  setSession,
  type AuthSession,
  type Schemas,
} from '@/api/client';
import { purgeUserCaches } from '@/lib/storage';

type State =
  | { status: 'loading'; user: null }
  | { status: 'signedOut'; user: null }
  | { status: 'signedIn'; user: Schemas['UserSummary'] };

type Ctx = State & {
  isNewAccount?: boolean;
  consumeNewAccount?: () => void;
  signIn: (email: string, password: string, totpCode?: string | null) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  signOut: (everywhere?: boolean) => Promise<void>;
};

const SessionCtx = createContext<Ctx | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: 'loading', user: null });
  const [isNewAccount, setIsNewAccount] = useState(false);
  const prevUserIdRef = useRef<string | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    ensureAuthChannel();
    const off = onSessionChange((s: AuthSession | null) => {
      const prevUid = prevUserIdRef.current;
      const nextUid = s?.user?.id ?? null;
      if (s) {
        if (prevUid && prevUid !== nextUid) {
          qc.clear();
          void purgeUserCaches(prevUid);
        }
        prevUserIdRef.current = nextUid;
        setState({ status: 'signedIn', user: s.user });
      } else {
        prevUserIdRef.current = null;
        setIsNewAccount(false);
        setState({ status: 'signedOut', user: null });
        qc.clear();
      }
    });
    refreshSession().then((s) => {
      if (!s) setState((cur) => (cur.status === 'loading' ? { status: 'signedOut', user: null } : cur));
    });
    return () => {
      off();
    };
  }, [qc]);

  const signIn = useCallback(async (email: string, password: string, totpCode?: string | null) => {
    bumpSessionEpoch();
    setIsNewAccount(false);
    const s = await call(
      api.POST('/auth/login', {
        body: { email, password, ...(totpCode ? { totp_code: totpCode } : {}) },
      }),
    );
    await setSession(s);
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    bumpSessionEpoch();
    const s = await call(api.POST('/auth/register', { body: { email, password } }));
    setIsNewAccount(true);
    await setSession(s);
  }, []);

  const signOut = useCallback(
    async (everywhere = false) => {
      const uid = prevUserIdRef.current ?? getCurrentUserId();
      bumpSessionEpoch();
      const token = currentRefreshToken();
      try {
        if (everywhere) {
          await call(api.POST('/auth/logout-all'));
        } else if (Platform.OS === 'web') {
          await call(
            api.POST('/auth/logout', {
              body: (token ? { refresh_token: token } : {}) as Schemas['LogoutRequest'],
            }),
          );
        } else if (token) {
          await call(api.POST('/auth/logout', { body: { refresh_token: token } }));
        }
      } catch {
        // signing out locally even when the server is unreachable
      }
      setIsNewAccount(false);
      await purgeUserCaches(uid);
      await setSession(null);
      qc.clear();
    },
    [qc],
  );

  const consumeNewAccount = useCallback(() => setIsNewAccount(false), []);

  const value = useMemo<Ctx>(
    () => ({ ...state, isNewAccount, consumeNewAccount, signIn, register, signOut }),
    [state, isNewAccount, consumeNewAccount, signIn, register, signOut],
  );
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}

export function useSession(): Ctx {
  const v = useContext(SessionCtx);
  if (!v) throw new Error('SessionProvider missing');
  return v;
}
