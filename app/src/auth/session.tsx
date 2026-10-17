import { useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import {
  api,
  call,
  currentRefreshToken,
  onSessionChange,
  refreshSession,
  setSession,
  type AuthSession,
  type Schemas,
} from '@/api/client';

type State =
  | { status: 'loading'; user: null }
  | { status: 'signedOut'; user: null }
  | { status: 'signedIn'; user: Schemas['UserSummary'] };

type Ctx = State & {
  signIn: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  signOut: (everywhere?: boolean) => Promise<void>;
};

const SessionCtx = createContext<Ctx | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: 'loading', user: null });
  const qc = useQueryClient();

  useEffect(() => {
    const off = onSessionChange((s: AuthSession | null) => {
      if (s) setState({ status: 'signedIn', user: s.user });
      else {
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

  const signIn = useCallback(async (email: string, password: string) => {
    const s = await call(api.POST('/auth/login', { body: { email, password } }));
    await setSession(s);
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    const s = await call(api.POST('/auth/register', { body: { email, password } }));
    await setSession(s);
  }, []);

  const signOut = useCallback(async (everywhere = false) => {
    const token = currentRefreshToken();
    try {
      if (everywhere) await call(api.POST('/auth/logout-all'));
      else if (token) await call(api.POST('/auth/logout', { body: { refresh_token: token } }));
    } catch {
      // signing out locally even when the server is unreachable
    }
    await setSession(null);
  }, []);

  const value = useMemo<Ctx>(() => ({ ...state, signIn, register, signOut }), [state, signIn, register, signOut]);
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}

export function useSession(): Ctx {
  const v = useContext(SessionCtx);
  if (!v) throw new Error('SessionProvider missing');
  return v;
}
