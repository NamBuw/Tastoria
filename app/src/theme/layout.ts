import { useWindowDimensions } from 'react-native';

import { space } from './tokens';

/**
 * Centralized responsive breakpoints for Mỹ Vị web + native surfaces.
 * Keeps individual `.tsx` screens free of duplicated inline width checks.
 */
export function useLayout() {
  const { width } = useWindowDimensions();
  const isCompactPhone = width < 380;
  const isTinyPhone = width < 360;
  const isMobile = width < 768;
  const isTabletUp = width >= 768;
  const isTablet = isTabletUp && width < 1024;
  const isWide = width >= 960;
  const isDesktop = width >= 1024;
  const padX = isTabletUp ? space.xl : space.lg;
  const recipeCols = isDesktop ? 3 : isTabletUp ? 2 : 1;
  const traySize = Math.min(width - 48, isDesktop ? 340 : 280);

  return {
    width,
    isCompactPhone,
    isTinyPhone,
    isMobile,
    isTablet,
    isTabletUp,
    isWide,
    isDesktop,
    padX,
    recipeCols,
    traySize,
  };
}

export function containerMaxWidth(width: number, variant: 'workspace' | 'focused'): number | undefined {
  if (variant === 'focused') return width >= 768 ? 680 : undefined;
  if (width >= 1024) return 1200;
  if (width >= 768) return 920;
  return undefined;
}
