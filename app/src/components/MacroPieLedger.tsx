import { StyleSheet, View } from 'react-native';
import Svg, { Circle, G } from 'react-native-svg';

import { hamiltonMacroShares } from '@/lib/caloriePlate';
import { font, radius, size, space, useTheme } from '@/theme';

import { StarAniseMark } from './Brand';
import { Row, T } from './ui';

export type MacroNutritionInput = {
  proteinG: number;
  carbsG: number;
  fatG: number;
  fiberG?: number | null;
  totalKcal?: number | null;
  massG?: number | null;
  sodiumMg?: number | null;
  sugarG?: number | null;
  nutritionGrade?: string | null;
  context?: 'meal' | 'daily' | 'snack';
};

export type MacroSlice = {
  key: 'carb' | 'protein' | 'lipid';
  label: string;
  grams: number;
  kcal: number;
  pct: number;
  amdrRange: string;
  inAmdr: boolean;
};

export type MacroAnalysis = {
  displayKcal: number;
  macroEnergyKcal: number;
  slices: MacroSlice[];
  fiberG: number;
  fiberDailyPct: number;
  densityKcalPer100g: number | null;
  densityTagVi: string | null;
  amdrBalanced: boolean;
  insightVi: string;
  warningsVi: string[];
};

function round1(v: number): number {
  if (!Number.isFinite(v)) return 0;
  return Math.max(0, Math.round(v * 10) / 10);
}

export function analyzeMacroNutrition(input: MacroNutritionInput): MacroAnalysis {
  const pG = round1(input.proteinG);
  const cG = round1(input.carbsG);
  const fG = round1(input.fatG);
  const fiberG = round1(input.fiberG ?? 0);

  const pKcalRaw = pG * 4;
  const cKcalRaw = cG * 4;
  const fKcalRaw = fG * 9;
  const rawEnergy = pKcalRaw + cKcalRaw + fKcalRaw;
  const hasMacroEnergy = rawEnergy > 0;

  const cKcal = Math.round(cKcalRaw);
  const pKcal = Math.round(pKcalRaw);
  const fKcal = Math.round(fKcalRaw);
  const macroEnergyKcal = cKcal + pKcal + fKcal;
  const displayKcal =
    input.totalKcal != null && Number.isFinite(input.totalKcal) && input.totalKcal > 0
      ? Math.round(input.totalKcal)
      : macroEnergyKcal;

  const { protein_pct: proteinPct, carbs_pct: carbPct, fat_pct: lipidPct } = hamiltonMacroShares(
    pKcalRaw,
    cKcalRaw,
    fKcalRaw,
  );

  const carbIn = hasMacroEnergy && carbPct >= 45 && carbPct <= 65;
  const proteinIn = hasMacroEnergy && proteinPct >= 15 && proteinPct <= 25;
  const lipidIn = hasMacroEnergy && lipidPct >= 20 && lipidPct <= 30;
  const amdrBalanced = hasMacroEnergy && carbIn && proteinIn && lipidIn;

  const slices: MacroSlice[] = [
    { key: 'carb', label: 'Tinh bột', grams: cG, kcal: cKcal, pct: carbPct, amdrRange: '45 đến 65%', inAmdr: carbIn },
    { key: 'protein', label: 'Chất đạm', grams: pG, kcal: pKcal, pct: proteinPct, amdrRange: '15 đến 25%', inAmdr: proteinIn },
    { key: 'lipid', label: 'Chất béo', grams: fG, kcal: fKcal, pct: lipidPct, amdrRange: '20 đến 30%', inAmdr: lipidIn },
  ];

  let densityKcalPer100g: number | null = null;
  let densityTagVi: string | null = null;
  if (input.massG != null && Number.isFinite(input.massG) && input.massG > 0 && displayKcal > 0) {
    densityKcalPer100g = Math.round((displayKcal / input.massG) * 100);
    if (densityKcalPer100g < 120) densityTagVi = 'Nhẹ bụng';
    else if (densityKcalPer100g <= 200) densityTagVi = 'Vừa năng lượng';
    else densityTagVi = 'Đậm năng lượng';
  }

  const fiberDailyPct = Math.min(200, Math.round((fiberG / 25) * 100));

  let insightVi: string;
  if (!hasMacroEnergy) {
    insightVi = 'Chưa có dữ liệu đa lượng chi tiết cho phần ăn này.';
  } else if (amdrBalanced) {
    insightVi =
      'Tỷ lệ Tinh bột, Chất đạm, Chất béo cân đối theo chuẩn Viện Dinh dưỡng Quốc gia và WHO (Tinh bột 45 đến 65%, Chất đạm 15 đến 25%, Chất béo 20 đến 30%).';
  } else if (lipidPct > 30) {
    insightVi = 'Chất béo vượt mức 30% năng lượng; có thể bớt dầu mỡ hoặc thêm rau luộc để cân bằng.';
  } else if (carbPct > 65 && proteinPct < 15) {
    insightVi = 'Tinh bột cao và đạm còn ít; thêm đậu phụ, trứng hoặc thịt nạc để no bền hơn.';
  } else if (carbPct > 65) {
    insightVi = 'Tinh bột vượt 65% năng lượng; thử giảm bớt cơm/bún và kèm thêm rau xanh.';
  } else if (proteinPct < 15) {
    insightVi = 'Tỷ lệ đạm dưới 15%; nên bổ sung thêm cá, thịt nạc, trứng hoặc đậu phụ.';
  } else if (proteinPct > 25 && carbPct < 45) {
    insightVi = 'Giàu đạm và ít tinh bột; phù hợp giữ cơ, có thể thêm chút cơm hoặc củ quả nếu vận động nhiều.';
  } else {
    insightVi = 'Cấu trúc năng lượng khá ổn; duy trì thêm rau xanh và uống đủ nước trong bữa.';
  }

  const warningsVi: string[] = [];
  if (input.sodiumMg != null && Number.isFinite(input.sodiumMg) && input.sodiumMg >= 700) {
    warningsVi.push(`Natri cao (~${Math.round(input.sodiumMg)} mg): hạn chế chấm thêm nước mắm hoặc ăn kèm rau nhạt.`);
  }
  if (input.sugarG != null && Number.isFinite(input.sugarG) && input.sugarG >= 15) {
    warningsVi.push(`Đường đơn cao (~${round1(input.sugarG)} g): nên hạn chế đồ uống ngọt kèm theo.`);
  }
  if (input.nutritionGrade === 'C' || input.nutritionGrade === 'D') {
    warningsVi.push('Món giàu năng lượng hoặc chế biến sẵn; nên kết hợp thêm rau xanh giàu chất xơ.');
  } else if (input.context !== 'snack' && displayKcal >= 250 && fiberG < 2.5) {
    warningsVi.push(`Chất xơ còn ít (${fiberG} g): thêm 1 đĩa rau luộc hoặc bát canh rau để hỗ trợ tiêu hoá.`);
  }

  return {
    displayKcal,
    macroEnergyKcal,
    slices,
    fiberG,
    fiberDailyPct,
    densityKcalPer100g,
    densityTagVi,
    amdrBalanced,
    insightVi,
    warningsVi,
  };
}

/**
 * Pure-SVG Donut/Pie Chart + Nutrition Facts Ledger (Carb, Protein, Lipid, Fiber, Energy Density & AMDR).
 */
export function MacroPieLedger({
  proteinG,
  carbsG,
  fatG,
  fiberG,
  totalKcal,
  massG,
  sodiumMg,
  sugarG,
  nutritionGrade,
  context = 'meal',
  title = 'Phân tích đa lượng & cân bằng dinh dưỡng',
}: MacroNutritionInput & { title?: string }) {
  const { c } = useTheme();
  const analysis = analyzeMacroNutrition({
    proteinG,
    carbsG,
    fatG,
    fiberG,
    totalKcal,
    massG,
    sodiumMg,
    sugarG,
    nutritionGrade,
    context,
  });

  const colorFor = (key: MacroSlice['key']) =>
    key === 'carb' ? c.macroChart.carb : key === 'protein' ? c.macroChart.protein : c.macroChart.lipid;

  const svgSize = 124;
  const cx = svgSize / 2;
  const cy = svgSize / 2;
  const r = 44;
  const strokeWidth = 18;
  const circumference = 2 * Math.PI * r;

  const activeSlices = analysis.slices.filter((s) => s.pct > 0);
  const segments = activeSlices.reduce<{ slice: MacroSlice; startPct: number }[]>((acc, slice) => {
    const prevEnd = acc.length > 0 ? acc[acc.length - 1].startPct + acc[acc.length - 1].slice.pct : 0;
    acc.push({ slice, startPct: prevEnd });
    return acc;
  }, []);

  return (
    <View
      testID="macro-nutrition-ledger"
      style={[
        styles.outerFrame,
        {
          borderColor: c.border,
          backgroundColor: c.surfaceCard,
        },
      ]}>
      <View
        style={[
          styles.innerDashed,
          {
            borderColor: c.borderDashed,
          },
        ]}>
        <View style={[styles.mastheadStrip, { borderBottomColor: c.borderDashed }]}>
          <Row gap={space.xs} style={{ flexShrink: 1, minWidth: 210, flexWrap: 'nowrap' }}>
            <StarAniseMark size={15} />
            <T
              v="h2"
              accessibilityRole="header"
              style={{ color: c.herb, fontFamily: font.displaySemibold, flexShrink: 1 }}>
              Phiếu phân tích dinh dưỡng
            </T>
          </Row>
          <T v="small" tone="muted" tabular style={{ flexShrink: 0 }}>
            Chuẩn Viện Dinh dưỡng Quốc gia và WHO
          </T>
        </View>

        <View
          style={[
            styles.ledger,
            {
              borderTopColor: c.border,
              borderBottomColor: c.border,
            },
          ]}>
          <View style={[styles.headerRow, { borderBottomColor: c.hairline }]}>
            <T v="label" style={{ flexShrink: 1, minWidth: 180 }}>
              {title}
            </T>
            <T v="small" tone="muted" tabular style={{ flexShrink: 0 }}>
              1g đạm, tinh bột ≈ 4 kcal, 1g béo ≈ 9 kcal
            </T>
          </View>

      {/* Chart + 3 Macro Breakdown Rows */}
      <View style={styles.chartAndRows}>
        <View style={styles.chartWrap}>
          <Svg
            testID="macro-pie-chart"
            width={svgSize}
            height={svgSize}
            viewBox={`0 0 ${svgSize} ${svgSize}`}
            accessibilityRole="image"
            accessibilityLabel={`Biểu đồ tròn đa lượng: Tinh bột ${analysis.slices[0].pct}%, Chất đạm ${analysis.slices[1].pct}%, Chất béo ${analysis.slices[2].pct}%`}>
            <Circle
              testID="macro-donut-outer-ring"
              cx={cx}
              cy={cy}
              r={r + strokeWidth / 2 + 3}
              fill="none"
              stroke={c.hairline}
              strokeWidth={1}
            />
            <Circle
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              stroke={c.surfaceAlt}
              strokeWidth={strokeWidth}
            />
            {activeSlices.length > 0 ? (
              <G rotation={-90} origin={`${cx}, ${cy}`}>
                {segments.map(({ slice: s, startPct }) => {
                  const segLen = (s.pct / 100) * circumference;
                  const gap = segments.length > 1 ? 2 : 0;
                  const dashLen = Math.max(0.5, segLen - gap);
                  const dashOffset = -((startPct / 100) * circumference);
                  return (
                    <Circle
                      key={s.key}
                      cx={cx}
                      cy={cy}
                      r={r}
                      fill="none"
                      stroke={colorFor(s.key)}
                      strokeWidth={strokeWidth}
                      strokeDasharray={`${dashLen} ${circumference}`}
                      strokeDashoffset={dashOffset}
                      strokeLinecap="butt"
                    />
                  );
                })}
              </G>
            ) : null}
            <Circle
              testID="macro-donut-inner-ring"
              cx={cx}
              cy={cy}
              r={r - strokeWidth / 2 - 3}
              fill="none"
              stroke={c.hairline}
              strokeWidth={1}
            />
          </Svg>
          <View pointerEvents="none" style={styles.donutCenter}>
            <T v="title" tabular style={{ fontFamily: font.displaySemibold, fontSize: size.lg, lineHeight: 22 }}>
              {analysis.displayKcal}
            </T>
            <T v="small" tone="muted" style={{ fontSize: 11, lineHeight: 14 }}>
              kcal
            </T>
          </View>
        </View>

        <View style={styles.rowsCol}>
          {analysis.slices.map((s, idx) => (
            <View
              key={s.key}
              style={[
                styles.macroRow,
                { borderTopColor: c.hairline, borderTopWidth: idx > 0 ? 1 : 0 },
              ]}
              accessibilityLabel={`${s.label}: ${s.grams} g, ${s.kcal} kcal, ${s.pct}%`}>
              <Row gap={space.xs} style={{ flex: 1, minWidth: 0, flexWrap: 'nowrap' }}>
                <View style={[styles.swatch, { backgroundColor: colorFor(s.key) }]} />
                <View style={{ flex: 1, minWidth: 0 }}>
                  <T v="label" numberOfLines={1}>
                    {s.label}
                  </T>
                  <T v="small" tone="muted" tabular>
                    Khuyến nghị {s.amdrRange}{s.inAmdr ? ', Đạt' : ''}
                  </T>
                </View>
              </Row>
              <View style={{ alignItems: 'flex-end', flexShrink: 0 }}>
                <T v="label" tabular>
                  {s.grams} g ({s.pct}%)
                </T>
                <T v="small" tone="muted" tabular>
                  {s.kcal} kcal
                </T>
              </View>
            </View>
          ))}
        </View>
      </View>

      {/* Fiber Progress Track */}
      <View style={[styles.subSection, { borderTopColor: c.hairline }]}>
        <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
          <Row gap={space.xs} style={{ flexWrap: 'nowrap' }}>
            <View style={[styles.swatch, { backgroundColor: c.macroChart.fiber }]} />
            <T v="label">Chất xơ</T>
          </Row>
          <T v="label" tabular>
            {analysis.fiberG} g ({analysis.fiberDailyPct}% / 25g ngày)
          </T>
        </Row>
        <View style={[styles.fiberTrack, { backgroundColor: c.surfaceAlt }]}>
          <View
            style={[
              styles.fiberFill,
              {
                width: `${Math.min(100, Math.max(analysis.fiberG > 0 ? 3 : 0, analysis.fiberDailyPct))}%`,
                backgroundColor: c.macroChart.fiber,
              },
            ]}
          />
        </View>
      </View>

      {/* Expanded Nutrition Facts Ledger: Energy Density + AMDR Insight + Quick Warnings */}
      <View style={[styles.subSection, { borderTopColor: c.hairline, gap: space.xs }]}>
        <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
          <T v="small" tone="muted">
            Mật độ năng lượng
          </T>
          <T v="label" tabular>
            {analysis.densityKcalPer100g != null
              ? `${analysis.densityKcalPer100g} kcal/100g, ${analysis.densityTagVi}`
              : 'Chưa rõ khối lượng (g)'}
          </T>
        </Row>

        <View style={[styles.insightRow, { borderTopColor: c.hairline }]}>
          <T v="small" tone={analysis.amdrBalanced ? 'herb' : 'text'}>
            {analysis.insightVi}
          </T>
        </View>

        {analysis.warningsVi.map((w, i) => (
          <View
            key={i}
            style={{
              backgroundColor: c.warnSoft,
              borderRadius: radius.sm,
              paddingHorizontal: space.sm,
              paddingVertical: 6,
            }}>
            <T v="small" tone="warn">
              {w}
            </T>
          </View>
        ))}
      </View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  outerFrame: {
    borderWidth: 1.5,
    borderRadius: radius.sm,
    padding: 4,
  },
  innerDashed: {
    borderWidth: 1,
    borderStyle: 'dashed',
    borderRadius: radius.sm,
    padding: space.md,
    gap: space.sm,
  },
  mastheadStrip: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    paddingBottom: space.xs,
    gap: space.sm,
  },
  ledger: {
    borderTopWidth: 2,
    borderBottomWidth: 1.5,
    paddingVertical: space.md,
    gap: space.md,
  },
  headerRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    paddingBottom: space.xs,
    borderBottomWidth: 1,
    gap: space.sm,
  },
  chartAndRows: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: space.md,
  },
  chartWrap: {
    width: 124,
    height: 124,
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  donutCenter: {
    position: 'absolute',
    alignItems: 'center',
    justifyContent: 'center',
  },
  rowsCol: {
    flex: 1,
    minWidth: 210,
  },
  macroRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 6,
    gap: space.sm,
  },
  swatch: {
    width: 10,
    height: 10,
    borderRadius: 2,
  },
  subSection: {
    borderTopWidth: 1,
    paddingTop: space.sm,
    gap: 6,
  },
  fiberTrack: {
    height: 6,
    borderRadius: 2,
    overflow: 'hidden',
  },
  fiberFill: {
    height: 6,
    borderRadius: 2,
  },
  insightRow: {
    borderTopWidth: 1,
    paddingTop: 6,
  },
});
