import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { View } from 'react-native';

import { api, call, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { useReference } from '@/lib/queries';
import { space } from '@/theme';

import { Chip, ErrorBox, Field, Loading, Radio, Row, Stepper, T } from './ui';

export const UNIT_LABEL: Record<string, string> = {
  qua: 'quả',
  bo: 'bó',
  cu: 'củ',
  nhanh: 'nhánh',
  mieng: 'miếng',
  goi: 'gói',
  hop: 'hộp',
  cay: 'cây',
  tep: 'tép',
  con: 'con',
};
export const LEVEL_LABEL = { it: 'Ít', vua: 'Vừa', nhieu: 'Nhiều' } as const;

type Ingredient = Schemas['Ingredient'];
type Qty = Schemas['QuantityInput'];

// ---- ingredient search --------------------------------------------------------------------------

export function IngredientSearch({
  onPick,
  picked,
  testID,
}: {
  onPick: (i: Ingredient) => void;
  picked?: Ingredient | null;
  testID?: string;
}) {
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const res = useQuery({
    queryKey: ['ingredients', debounced],
    queryFn: () => call(api.GET('/ingredients', { params: { query: { q: debounced, limit: 12 } } })),
    enabled: debounced.length >= 1,
  });
  return (
    <View style={{ gap: space.sm }}>
      <Field label="Nguyên liệu" testID={testID} value={q} onChangeText={setQ} placeholder="Gõ tên, ví dụ: trứng, rau muống" autoCapitalize="none" />
      {res.isFetching ? <Loading label="Đang tìm…" /> : null}
      {res.error ? <ErrorBox message={errorText(res.error)} /> : null}
      {res.data ? (
        res.data.items.length ? (
          <Row>
            {res.data.items.map((i) => (
              <Chip key={i.id} testID={`ing-${i.name_vi}`} label={i.name_vi} selected={picked?.id === i.id} onPress={() => onPick(i)} />
            ))}
          </Row>
        ) : (
          <T tone="muted">Không thấy nguyên liệu &quot;{debounced}&quot; trong danh mục.</T>
        )
      ) : null}
    </View>
  );
}

// ---- quantity -----------------------------------------------------------------------------------

type Mode = 'count' | 'level' | 'grams';

/**
 * The three ways to give an amount (QuantityInput): count × unit (any `ingredient_units` row), ít/vừa/nhiều
 * (only for non-countable ingredients), or grams. The server converts to [g_min, g_max].
 */
export function QuantityEditor({ ingredient, onChange }: { ingredient: Ingredient; onChange: (q: Qty | null) => void }) {
  const ref = useReference();
  const modes: Mode[] = [
    ...(ingredient.units.length ? (['count'] as const) : []),
    ...(!ingredient.countable ? (['level'] as const) : []),
    'grams',
  ];
  const [mode, setMode] = useState<Mode>(modes[0]);
  const [count, setCount] = useState(1);
  const [unit, setUnit] = useState(ingredient.units[0]?.unit_code ?? '');
  const [level, setLevel] = useState<'it' | 'vua' | 'nhieu' | null>(null);
  const [grams, setGrams] = useState('');

  useEffect(() => {
    if (mode === 'count' && unit) onChange({ count, unit_code: unit });
    else if (mode === 'level') onChange(level ? { qty_level: level } : null);
    else if (mode === 'grams') {
      const g = Number(grams.replace(',', '.'));
      onChange(grams && g > 0 ? { g_min: g, g_max: g } : null);
    } else onChange(null);
  }, [mode, count, unit, level, grams, onChange]);

  const levels = (ref.data?.qty_levels ?? []).filter((l) => l.food_group_code === ingredient.food_group_code);
  const unitInfo = ingredient.units.find((u) => u.unit_code === unit);

  return (
    <View style={{ gap: space.md }}>
      {modes.length > 1 ? (
        <Row>
          {modes.map((m) => (
            <Radio
              key={m}
              label={m === 'count' ? 'Đếm' : m === 'level' ? 'Ít / vừa / nhiều' : 'Theo gam'}
              selected={mode === m}
              onPress={() => setMode(m)}
            />
          ))}
        </Row>
      ) : null}
      {mode === 'count' ? (
        <>
          <Stepper label="Số lượng" value={count} onChange={setCount} min={1} max={99} testID="qty-count" />
          {ingredient.units.length > 1 ? (
            <Row>
              {ingredient.units.map((u) => (
                <Radio key={u.unit_code} label={UNIT_LABEL[u.unit_code] ?? u.unit_code} selected={unit === u.unit_code} onPress={() => setUnit(u.unit_code)} />
              ))}
            </Row>
          ) : null}
          {unitInfo ? (
            <T v="small" tone="muted">
              1 {UNIT_LABEL[unitInfo.unit_code] ?? unitInfo.unit_code} ≈ {Math.round(unitInfo.grams_per_unit)} g ({unitInfo.source})
            </T>
          ) : null}
        </>
      ) : null}
      {mode === 'level' ? (
        <Row>
          {(['it', 'vua', 'nhieu'] as const).map((l) => {
            const info = levels.find((x) => x.level === l);
            return (
              <Radio
                key={l}
                label={`${LEVEL_LABEL[l]}${info ? ` (${Math.round(info.g_min)}–${Math.round(info.g_max)} g)` : ''}`}
                selected={level === l}
                onPress={() => setLevel(l)}
              />
            );
          })}
        </Row>
      ) : null}
      {mode === 'grams' ? (
        <Field
          label="Khối lượng (g)"
          testID="qty-grams"
          value={grams}
          onChangeText={setGrams}
          keyboardType="decimal-pad"
          inputMode="decimal"
        />
      ) : null}
    </View>
  );
}

// ---- purchase date -------------------------------------------------------------------------------

/** Purchase date as "n ngày trước" chips; null = không nhớ (server uses first_seen, BR-PANTRY-01). */
export function PurchaseDate({ value, onChange }: { value: number | null; onChange: (daysAgo: number | null) => void }) {
  const opts: { v: number | null; l: string }[] = [
    { v: 0, l: 'Hôm nay' },
    { v: 1, l: 'Hôm qua' },
    { v: 2, l: '2 ngày trước' },
    { v: 3, l: '3 ngày trước' },
    { v: 5, l: '5 ngày trước' },
    { v: 7, l: '1 tuần trước' },
    { v: null, l: 'Không nhớ' },
  ];
  return (
    <View style={{ gap: space.xs }}>
      <T v="label">Ngày mua</T>
      <Row>
        {opts.map((o) => (
          <Radio key={String(o.v)} label={o.l} selected={value === o.v} onPress={() => onChange(o.v)} />
        ))}
      </Row>
    </View>
  );
}

export function daysAgoIso(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  if (n > 0) d.setHours(12, 0, 0, 0);
  else d.setMinutes(d.getMinutes() - 1); // never in the future (acquired_at_in_future)
  return d.toISOString();
}
