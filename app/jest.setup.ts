/// <reference types="jest" />
/* eslint-disable @typescript-eslint/no-require-imports */
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

jest.mock('react-native-safe-area-context', () => {
  const React = require('react');
  const { View } = require('react-native');
  const inset = { top: 0, right: 0, bottom: 0, left: 0 };
  const frame = { x: 0, y: 0, width: 390, height: 844 };
  return {
    SafeAreaProvider: ({ children }: { children: React.ReactNode }) => children,
    SafeAreaView: ({ children, style, testID }: { children: React.ReactNode; style?: object; testID?: string }) =>
      React.createElement(View, { style, testID }, children),
    useSafeAreaInsets: () => inset,
    useSafeAreaFrame: () => frame,
    initialWindowMetrics: { insets: inset, frame },
  };
});

jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { version: '0.1.4' } },
}));

let mockUuidCounter = 0;
jest.mock('expo-crypto', () => ({
  randomUUID: jest.fn(() => {
    mockUuidCounter += 1;
    return `00000000-0000-4000-8000-${String(mockUuidCounter).padStart(12, '0')}`;
  }),
}));

const mockSecureStore = new Map<string, string>();
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async (key: string) => mockSecureStore.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, val: string) => {
    mockSecureStore.set(key, val);
  }),
  deleteItemAsync: jest.fn(async (key: string) => {
    mockSecureStore.delete(key);
  }),
}));

jest.mock('expo-image', () => {
  const React = require('react');
  const { Text, View } = require('react-native');
  return {
    Image: ({
      accessibilityLabel,
      testID,
      source,
      style,
    }: {
      accessibilityLabel?: string;
      testID?: string;
      source?: unknown;
      style?: object;
    }) =>
      React.createElement(
        View,
        { accessibilityLabel, testID, style },
        typeof source === 'object' && source && 'uri' in source
          ? React.createElement(Text, null, String((source as { uri?: string }).uri ?? ''))
          : null,
      ),
  };
});

jest.mock('expo-image-picker', () => ({
  requestCameraPermissionsAsync: jest.fn(async () => ({ granted: true })),
  launchCameraAsync: jest.fn(async () => ({ canceled: true, assets: [] })),
  launchImageLibraryAsync: jest.fn(async () => ({ canceled: true, assets: [] })),
}));

jest.mock('expo-image-manipulator', () => {
  const makeRef = (uri: string) => ({
    width: 800,
    height: 600,
    saveAsync: jest.fn(async () => ({ uri, width: 800, height: 600 })),
  });
  interface MockImageCtx {
    resize: jest.Mock<MockImageCtx, []>;
    renderAsync: jest.Mock<Promise<{ width: number; height: number; saveAsync: jest.Mock }>, []>;
  }
  const makeCtx = (uri: string): MockImageCtx => ({
    resize: jest.fn((): MockImageCtx => makeCtx(uri)),
    renderAsync: jest.fn(async () => makeRef(uri)),
  });
  return {
    SaveFormat: { JPEG: 'jpeg', PNG: 'png', WEBP: 'webp' },
    ImageManipulator: {
      manipulate: jest.fn((uri: string) => makeCtx(uri)),
    },
    manipulateAsync: jest.fn(async (uri: string) => ({ uri, width: 800, height: 600 })),
  };
});

jest.mock('expo-keep-awake', () => ({
  useKeepAwake: jest.fn(),
  activateKeepAwakeAsync: jest.fn(async () => {}),
  deactivateKeepAwake: jest.fn(async () => {}),
}));

jest.mock('react-native-svg', () => {
  const React = require('react');
  const { View } = require('react-native');
  const mk = (name: string) => {
    const Comp = ({ children, ...props }: { children?: React.ReactNode; [k: string]: unknown }) =>
      React.createElement(View, { ...props, accessibilityRole: props.accessibilityRole ?? undefined }, children);
    Comp.displayName = name;
    return Comp;
  };
  return {
    __esModule: true,
    default: mk('Svg'),
    Svg: mk('Svg'),
    Path: mk('Path'),
    Rect: mk('Rect'),
    Circle: mk('Circle'),
    Line: mk('Line'),
    Polyline: mk('Polyline'),
    Polygon: mk('Polygon'),
    G: mk('G'),
  };
});

export const mockRouter = {
  push: jest.fn(),
  replace: jest.fn(),
  back: jest.fn(),
};
export const mockNavState = {
  segments: ['(tabs)', 'bep'] as string[],
  pathname: '/bep',
  params: {} as Record<string, string>,
};

jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useNavigation: () => ({ setOptions: jest.fn() }),
  useSegments: () => mockNavState.segments,
  usePathname: () => mockNavState.pathname,
  useLocalSearchParams: () => mockNavState.params,
}));

export const mockSessionState = {
  status: 'signedIn' as 'loading' | 'signedOut' | 'signedIn',
  user: {
    id: 'user-1',
    email: 'bep@tastoria.vn',
    role: 'user' as 'user' | 'curator' | 'ml_operator' | 'admin',
    onboarding_completed: true,
  } as {
    id: string;
    email: string;
    role: 'user' | 'curator' | 'ml_operator' | 'admin';
    onboarding_completed: boolean;
  } | null,
  signIn: jest.fn(async () => {}),
  register: jest.fn(async () => {}),
  signOut: jest.fn(async () => {}),
};

jest.mock('@/auth/session', () => ({
  useSession: () => mockSessionState,
  SessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

beforeEach(() => {
  mockUuidCounter = 0;
  mockSecureStore.clear();
  mockRouter.push.mockClear();
  mockRouter.replace.mockClear();
  mockRouter.back.mockClear();
  mockNavState.segments = ['(tabs)', 'bep'];
  mockNavState.pathname = '/bep';
  mockNavState.params = {};
  mockSessionState.status = 'signedIn';
  mockSessionState.user = {
    id: 'user-1',
    email: 'bep@tastoria.vn',
    role: 'user',
    onboarding_completed: true,
  };
  mockSessionState.signOut.mockClear();
});
