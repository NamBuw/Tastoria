import type { Schemas } from '@/api/client';

export type SuggestedModifier = {
  id: string;
  label_vi: string;
  kcal_delta: number;
  fat_delta_g: number;
  carbs_delta_g: number;
  protein_delta_g: number;
  fiber_delta_g?: number;
  mass_delta_g?: number;
};

export type MealCalorieEstimateView = Omit<Schemas['MealCalorieEstimateOut'], 'source'> & {
  source: Schemas['MealCalorieEstimateOut']['source'] | string;
  disambiguation_required?: boolean;
  top_margin?: number | null;
  provenance_label_vi?: string | null;
  fusion_mode?: string | null;
  suggested_modifiers?: SuggestedModifier[];
};

export const VN_MEAL_MODIFIERS: readonly SuggestedModifier[] = [
  {
    id: 'mo_hanh',
    label_vi: 'Thêm mỡ hành',
    kcal_delta: 80,
    fat_delta_g: 8,
    carbs_delta_g: 2,
    protein_delta_g: 0.5,
    mass_delta_g: 15,
  },
  {
    id: 'nuoc_mam_pha',
    label_vi: 'Chan nước mắm pha',
    kcal_delta: 45,
    fat_delta_g: 0,
    carbs_delta_g: 10,
    protein_delta_g: 1,
    mass_delta_g: 25,
  },
  {
    id: 'it_com_bun',
    label_vi: 'Ít cơm/bún',
    kcal_delta: -95,
    fat_delta_g: -0.5,
    carbs_delta_g: -21,
    protein_delta_g: -2,
    mass_delta_g: -70,
  },
  {
    id: 'trung_op_la',
    label_vi: 'Thêm 1 trứng ốp la',
    kcal_delta: 95,
    fat_delta_g: 7,
    carbs_delta_g: 0.6,
    protein_delta_g: 6.5,
    mass_delta_g: 55,
  },
  {
    id: 'it_dau_mo',
    label_vi: 'Ít dầu mỡ / luộc',
    kcal_delta: -75,
    fat_delta_g: -8,
    carbs_delta_g: 0,
    protein_delta_g: 0,
    mass_delta_g: -10,
  },
];

function normLabel(s: string): string {
  return s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .trim()
    .replace(/\s+/g, ' ');
}

export function mergeModifiers(apiModifiers?: SuggestedModifier[] | null): SuggestedModifier[] {
  const out: SuggestedModifier[] = [];
  const seenIds = new Set<string>();
  const seenLabels = new Set<string>();

  for (const mod of [...(apiModifiers ?? []), ...VN_MEAL_MODIFIERS]) {
    const nLabel = normLabel(mod.label_vi);
    if (seenIds.has(mod.id) || seenLabels.has(nLabel)) continue;
    seenIds.add(mod.id);
    seenLabels.add(nLabel);
    out.push(mod);
  }
  return out;
}

/** Hamilton largest-remainder rounding so non-zero macro percentages sum to exactly 100. */
export function hamiltonMacroShares(
  proteinKcal: number,
  carbsKcal: number,
  fatKcal: number,
): { protein_pct: number; carbs_pct: number; fat_pct: number } {
  const vals = [
    Number.isFinite(proteinKcal) ? Math.max(0, proteinKcal) : 0,
    Number.isFinite(carbsKcal) ? Math.max(0, carbsKcal) : 0,
    Number.isFinite(fatKcal) ? Math.max(0, fatKcal) : 0,
  ];
  const total = vals[0] + vals[1] + vals[2];
  if (total <= 0) return { protein_pct: 0, carbs_pct: 0, fat_pct: 0 };
  const exact = vals.map((v) => (v / total) * 100);
  const floors = exact.map((e) => Math.floor(e));
  const rem = 100 - (floors[0] + floors[1] + floors[2]);
  const order = [0, 1, 2].sort((a, b) => exact[b] - floors[b] - (exact[a] - floors[a]));
  for (let i = 0; i < rem; i += 1) {
    floors[order[i % 3]] += 1;
  }
  return { protein_pct: floors[0], carbs_pct: floors[1], fat_pct: floors[2] };
}

export type AdjustedPlateMetrics = {
  estimated_kcal: number;
  kcal_low: number;
  kcal_high: number;
  estimated_mass_g: number | null;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  macro_kcal_split: Schemas['MacroKcalSplitOut'] | null;
  activeModifiers: SuggestedModifier[];
};

export function applyPlateModifiers(
  est: MealCalorieEstimateView,
  activeModIds: string[],
  availableModifiers?: SuggestedModifier[],
): AdjustedPlateMetrics {
  const pool = availableModifiers ?? mergeModifiers(est.suggested_modifiers);
  const activeSet = new Set(activeModIds);
  const activeModifiers = pool.filter((m) => activeSet.has(m.id));

  let dKcal = 0;
  let dP = 0;
  let dC = 0;
  let dF = 0;
  let dFiber = 0;
  let dMass = 0;
  for (const m of activeModifiers) {
    dKcal += m.kcal_delta;
    dP += m.protein_delta_g;
    dC += m.carbs_delta_g;
    dF += m.fat_delta_g;
    dFiber += m.fiber_delta_g ?? 0;
    dMass += m.mass_delta_g ?? 0;
  }

  const estimated_kcal = Math.max(0, Math.round(est.estimated_kcal + dKcal));
  const kcal_low = Math.max(0, Math.round(est.kcal_low + dKcal));
  const kcal_high = Math.max(kcal_low, Math.round(est.kcal_high + dKcal));
  const estimated_mass_g =
    est.estimated_mass_g != null && est.estimated_mass_g > 0
      ? Math.max(20, Math.round(est.estimated_mass_g + dMass))
      : null;

  const round1 = (x: number) => (Number.isFinite(x) ? Math.max(0, Math.round(x * 10) / 10) : 0);
  const protein_g = round1(est.protein_g + dP);
  const carbs_g = round1(est.carbs_g + dC);
  const fat_g = round1(est.fat_g + dF);
  const fiber_g = round1((est.fiber_g ?? 0) + dFiber);

  const pKcal = protein_g * 4;
  const cKcal = carbs_g * 4;
  const fKcal = fat_g * 9;
  const totalMacroKcal = pKcal + cKcal + fKcal;

  const macro_kcal_split: Schemas['MacroKcalSplitOut'] | null =
    totalMacroKcal > 0 ? hamiltonMacroShares(pKcal, cKcal, fKcal) : null;

  return {
    estimated_kcal,
    kcal_low,
    kcal_high,
    estimated_mass_g,
    protein_g,
    carbs_g,
    fat_g,
    fiber_g,
    macro_kcal_split,
    activeModifiers,
  };
}

const LEAKED_DATASET_RE = new RegExp('nutrition[\\s_-]*5k', 'gi');
const LEAKED_BRAND_RE = new RegExp('yuka[a-z0-9_-]*', 'gi');

export function sanitizeProvenanceText(text?: string | null): string {
  if (!text) return '';
  return text
    .replace(LEAKED_DATASET_RE, 'mô hình trực quan')
    .replace(LEAKED_BRAND_RE, 'chỉ số Mỹ Vị')
    .replace(/\s*[·•—–|]\s*/g, ', ')
    .trim();
}

export function resolveProvenanceLabel(est: MealCalorieEstimateView): string {
  if (est.provenance_label_vi && est.provenance_label_vi.trim()) {
    return sanitizeProvenanceText(est.provenance_label_vi);
  }
  if (est.source === 'hybrid') return 'Viện Dinh dưỡng Quốc gia & Ảnh';
  if (est.source === 'kb_calibrated') return 'Bảng thực phẩm Việt & Quốc tế';
  return 'Ước lượng trực quan theo khẩu phần';
}

export function needsDisambiguation(est: MealCalorieEstimateView): {
  required: boolean;
  c1?: Schemas['DishCandidateOut'];
  c2?: Schemas['DishCandidateOut'];
} {
  const cands = est.top_candidates ?? [];
  if (cands.length < 2) return { required: false };
  const [c1, c2] = cands;
  const margin = est.top_margin ?? c1.confidence - c2.confidence;
  const topConf = est.recognized_confidence ?? c1.confidence;
  const required = est.disambiguation_required === true || margin < 0.12 || topConf < 0.55;
  return required ? { required: true, c1, c2 } : { required: false };
}

export function formatModifierDelta(delta: number): string {
  const rounded = Math.round(delta);
  return rounded >= 0 ? `+${rounded} kcal` : `${rounded} kcal`;
}
