import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * Onboarding progress per user (FR-09-12: reopen at the first step the server has not confirmed).
 * Only steps that got a 2xx are recorded here.
 */
export type OnboardingProgress = { consent: boolean; step: number; done: boolean };

const key = (userId: string) => `tastoria.onboarding.${userId}`;

export async function getProgress(userId: string): Promise<OnboardingProgress> {
  try {
    const raw = await AsyncStorage.getItem(key(userId));
    if (raw) return JSON.parse(raw) as OnboardingProgress;
  } catch {
    // ignore
  }
  return { consent: false, step: 0, done: false };
}

export async function saveProgress(userId: string, p: Partial<OnboardingProgress>): Promise<void> {
  const cur = await getProgress(userId);
  try {
    await AsyncStorage.setItem(key(userId), JSON.stringify({ ...cur, ...p }));
  } catch {
    // ignore
  }
}
