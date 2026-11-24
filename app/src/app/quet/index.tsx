import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as ImagePicker from 'expo-image-picker';
import { Image } from 'expo-image';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, View } from 'react-native';

import { api, ApiError, call, isCode, type Schemas } from '@/api/client';
import { errorText } from '@/api/errors';
import { useSession } from '@/auth/session';
import { Icon } from '@/components/domain';
import { MacroPieLedger } from '@/components/MacroPieLedger';
import {
  Button,
  Card,
  Checkbox,
  ErrorBox,
  Field,
  HairlineSegmented,
  Notice,
  ReceiptCheckRow,
  Row,
  Screen,
  Segmented,
  T,
  UnderlineTabs,
} from '@/components/ui';
import {
  applyPlateModifiers,
  formatModifierDelta,
  type MealCalorieEstimateView,
  mergeModifiers,
  needsDisambiguation,
  resolveProvenanceLabel,
  sanitizeProvenanceText,
} from '@/lib/caloriePlate';
import { useIdempotencyKey } from '@/lib/idempotency';
import { imagePart, prepareImage, type PreparedImage } from '@/lib/image';
import {
  addQuickMealLog,
  defaultMealSlot,
  MEAL_SLOT_LABEL,
  MEAL_SLOTS,
  type MealSlot,
  type QuickMealLogEntry,
  removeQuickMealLog,
} from '@/lib/mealLog';
import { goTab } from '@/lib/nav';
import { useHasConsent, useProfile } from '@/lib/queries';
import { radius, space, useLayout, useTheme } from '@/theme';

type ScanSection = 'ingredients' | 'calorie' | 'barcode';
type Portion = Schemas['MealCalorieEstimateOut']['portion'];

const PLATE_PORTIONS: readonly (readonly [Portion, string])[] = [
  ['nho', 'Nhỏ 0.75×'],
  ['vua', 'Vừa 1.0×'],
  ['lon', 'Lớn 1.35×'],
];

const QUICK_FOOD_QUERIES = ['Phở', 'Cơm tấm', 'Mì Hảo Hảo', 'Bún thịt nướng', 'Trà sữa'];

function gradeTone(grade?: 'A' | 'B' | 'C' | 'D' | string | null): {
  label: string;
  bgKey: 'herbSoft' | 'infoSoft' | 'warnSoft' | 'dangerSoft' | 'surfaceAlt';
  fgKey: 'herb' | 'info' | 'warn' | 'danger' | 'muted';
} {
  if (grade === 'A') return { label: 'Cân bằng tốt', bgKey: 'herbSoft', fgKey: 'herb' };
  if (grade === 'B') return { label: 'Khá cân đối', bgKey: 'infoSoft', fgKey: 'info' };
  if (grade === 'C') return { label: 'Năng lượng vừa', bgKey: 'warnSoft', fgKey: 'warn' };
  if (grade === 'D') return { label: 'Năng lượng cao', bgKey: 'dangerSoft', fgKey: 'danger' };
  return { label: 'Đang cập nhật', bgKey: 'surfaceAlt', fgKey: 'muted' };
}

const QUICK_BARCODES: readonly (readonly [string, string])[] = [
  ['8934563138165', 'Mì Hảo Hảo'],
  ['8936017360015', 'Mì Omachi'],
  ['089686170726', 'Indomie'],
  ['8934673100113', 'Sữa Vinamilk'],
];

function foldText(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase();
}

function resolveBarcodeActiveNutrition(
  bcOut: Schemas['BarcodeNutritionOut'],
  bcUnit: 'serving' | '100g',
): {
  use100g: boolean;
  kcal: number;
  hasKcal: boolean;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  portion_label: string;
  mass_g: number | null;
} {
  const hasServing = bcOut.kcal_per_serving != null;
  const has100g = bcOut.kcal_per_100g != null;
  const use100g = (bcUnit === '100g' && has100g) || (!hasServing && has100g);
  const rawKcal = use100g ? bcOut.kcal_per_100g : bcOut.kcal_per_serving ?? bcOut.kcal_per_100g;
  const round1 = (v: number | null | undefined) => Math.round((v ?? 0) * 10) / 10;
  return {
    use100g,
    hasKcal: rawKcal != null,
    kcal: Math.round(rawKcal ?? 0),
    protein_g: round1(use100g ? bcOut.protein_g_per_100g : bcOut.protein_g_per_serving ?? bcOut.protein_g_per_100g),
    carbs_g: round1(use100g ? bcOut.carbs_g_per_100g : bcOut.carbs_g_per_serving ?? bcOut.carbs_g_per_100g),
    fat_g: round1(use100g ? bcOut.fat_g_per_100g : bcOut.fat_g_per_serving ?? bcOut.fat_g_per_100g),
    fiber_g: round1(use100g ? bcOut.fiber_g_per_100g : bcOut.fiber_g_per_serving ?? bcOut.fiber_g_per_100g),
    portion_label: use100g ? '100 g' : bcOut.serving_size ?? '1 phần',
    mass_g: use100g ? 100 : bcOut.serving_g ?? null,
  };
}

/** Quét (UC12 + UC22): Quét nguyên liệu tủ lạnh, Nhận diện & đo calo món ăn, và Quét mã vạch. */
export default function Scan() {
  const { c } = useTheme();
  const { isDesktop } = useLayout();
  const { user } = useSession();
  const qc = useQueryClient();
  const profile = useProfile();
  const router = useRouter();
  const params = useLocalSearchParams<{ mode?: string; tab?: string }>();

  const paramTab: ScanSection =
    params.tab === 'calorie' ? 'calorie' : params.tab === 'barcode' ? 'barcode' : 'ingredients';
  const [tabPick, setTabPick] = useState<{ base: string | undefined; value: ScanSection } | null>(null);
  const section: ScanSection = tabPick && tabPick.base === params.tab ? tabPick.value : paramTab;
  const setSection = (value: ScanSection) => setTabPick({ base: params.tab, value });

  // ---- Tab 1: Nguyên liệu tủ lạnh / đồ vừa mua ----
  const paramMode: Schemas['ScanMode'] = params.mode === 'haul' ? 'haul' : 'fridge';
  const [modePick, setModePick] = useState<{ base: string | undefined; value: Schemas['ScanMode'] } | null>(null);
  const mode: Schemas['ScanMode'] = modePick && modePick.base === params.mode ? modePick.value : paramMode;
  const setMode = (value: Schemas['ScanMode']) => setModePick({ base: params.mode, value });
  const [images, setImages] = useState<PreparedImage[]>([]);
  const [contribute, setContribute] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [notOpen, setNotOpen] = useState(false);
  const photoConsent = useHasConsent('photo_contribution');
  const idem = useIdempotencyKey();

  // ---- Tab 2: Món ăn & Calo (ảnh + tìm món Việt, mì gói, đồ uống) ----
  const [mealImg, setMealImg] = useState<PreparedImage | null>(null);
  const [portion, setPortion] = useState<Portion>('vua');
  const [dishQuery, setDishQuery] = useState('');
  const [selectedDishSlug, setSelectedDishSlug] = useState<string | null>(null);
  const [calBusy, setCalBusy] = useState(false);
  const [calErr, setCalErr] = useState<unknown>(null);
  const [calOut, setCalOut] = useState<MealCalorieEstimateView | null>(null);
  const [activeModIds, setActiveModIds] = useState<string[]>([]);
  const [calSlot, setCalSlot] = useState<MealSlot>(() => defaultMealSlot());
  const [loggedCalEntry, setLoggedCalEntry] = useState<QuickMealLogEntry | null>(null);
  const [calLogBusy, setCalLogBusy] = useState(false);
  const [calLogErr, setCalLogErr] = useState<unknown>(null);
  const calLogBusyRef = useRef(false);
  const calLogIdem = useIdempotencyKey();
  const calReqSeq = useRef(0);
  const calAbortRef = useRef<AbortController | null>(null);
  const lastCalQueryRef = useRef<{ img: PreparedImage | null; dishName: string; dishSlug: string | null } | null>(null);

  useEffect(() => () => calAbortRef.current?.abort(), []);

  const dishesQuery = useQuery({
    queryKey: ['meal-calorie-dishes-ext'],
    queryFn: () => call(api.GET('/meal-calorie/dishes', { params: { query: { include_extended: true } } })),
    enabled: section === 'calorie',
    staleTime: 5 * 60 * 1000,
  });

  const matchingDishes = useMemo(() => {
    const all = dishesQuery.data?.dishes ?? [];
    const q = foldText(dishQuery.trim());
    if (!q) return [];
    return all.filter((d) => foldText(d.name_vi).includes(q) || foldText(d.slug).includes(q)).slice(0, 8);
  }, [dishesQuery.data, dishQuery]);

  // ---- Tab 3: Mã vạch sản phẩm đóng gói ----
  const [barcode, setBarcode] = useState('');
  const [bcBusy, setBcBusy] = useState(false);
  const [bcErr, setBcErr] = useState<unknown>(null);
  const [bcNote, setBcNote] = useState<string | null>(null);
  const [bcOut, setBcOut] = useState<Schemas['BarcodeNutritionOut'] | null>(null);
  const [bcUnit, setBcUnit] = useState<'serving' | '100g'>('serving');
  const [bcSlot, setBcSlot] = useState<MealSlot>(() => defaultMealSlot());
  const [loggedBcEntry, setLoggedBcEntry] = useState<QuickMealLogEntry | null>(null);
  const [bcLogBusy, setBcLogBusy] = useState(false);
  const [bcLogErr, setBcLogErr] = useState<unknown>(null);
  const bcLogBusyRef = useRef(false);
  const bcLogIdem = useIdempotencyKey();

  const add = async (camera: boolean) => {
    setErr(null);
    const opts: ImagePicker.ImagePickerOptions = {
      mediaTypes: ['images'],
      quality: 1,
      allowsMultipleSelection: !camera,
      selectionLimit: 2 - images.length,
    };
    if (camera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        setErr(new Error('camera'));
        return;
      }
    }
    const res = camera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (res.canceled) return;
    setBusy(true);
    try {
      const prepared = await Promise.all(res.assets.slice(0, 2 - images.length).map((a) => prepareImage(a.uri)));
      setImages((s) => [...s, ...prepared].slice(0, 2));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    setBusy(true);
    setErr(null);
    const shouldContribute = contribute && photoConsent;
    try {
      const key = idem.keyFor({ mode, images: images.map((i) => i.uri), contribute: shouldContribute });
      const parts = await Promise.all(images.map((img, i) => imagePart(img, `anh-${i + 1}.jpg`)));
      const accepted = await call(
        api.POST('/scans', {
          params: { header: { 'Idempotency-Key': key } },
          body: { mode, images: [], contribute: shouldContribute } as unknown as Schemas['ScanCreate'],
          bodySerializer: () => {
            const fd = new FormData();
            fd.append('mode', mode);
            fd.append('contribute', String(shouldContribute));
            parts.forEach((p, i) => fd.append('images', p as Blob, `anh-${i + 1}.jpg`));
            return fd;
          },
        }),
      );
      idem.reset();
      router.replace({ pathname: '/quet/[id]', params: { id: accepted.id } });
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && !isCode(e, 'idempotency_in_progress')) {
        idem.reset();
      }
      if (isCode(e, 'not_found')) setNotOpen(true);
      else setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const estimateMeal = async (opts?: {
    img?: PreparedImage | null;
    dishName?: string;
    dishSlug?: string | null;
    nextPortion?: Portion;
    preserveModifiers?: boolean;
  }) => {
    const imgToSend = opts && 'img' in opts ? opts.img : mealImg;
    const hasExplicitDishName = opts != null && 'dishName' in opts;
    const rawDishName = hasExplicitDishName ? opts.dishName : dishQuery;
    const nameToSend = rawDishName?.trim() || undefined;
    const hasExplicitSlug = opts != null && 'dishSlug' in opts;
    const slugToSend = (hasExplicitSlug ? opts.dishSlug : selectedDishSlug)?.trim() || undefined;
    const portToSend = opts?.nextPortion ?? portion;
    if (!imgToSend && !nameToSend && !slugToSend) return;

    calAbortRef.current?.abort();
    const ctrl = new AbortController();
    calAbortRef.current = ctrl;
    const seq = ++calReqSeq.current;
    lastCalQueryRef.current = {
      img: imgToSend ?? null,
      dishName: nameToSend ?? '',
      dishSlug: slugToSend ?? null,
    };

    setCalBusy(true);
    setCalErr(null);
    try {
      const part = imgToSend ? await imagePart(imgToSend, 'mon-an.jpg') : null;
      if (ctrl.signal.aborted || seq !== calReqSeq.current) return;
      const out = (await call(
        api.POST('/meal-calorie/estimate', {
          body: { portion: portToSend } as never,
          signal: ctrl.signal,
          bodySerializer: () => {
            const fd = new FormData();
            fd.append('portion', portToSend);
            if (part) fd.append('image', part as Blob, 'mon-an.jpg');
            if (slugToSend) fd.append('dish_slug', slugToSend);
            if (nameToSend) fd.append('dish_name', nameToSend);
            return fd;
          },
        }),
      )) as MealCalorieEstimateView;
      if (ctrl.signal.aborted || seq !== calReqSeq.current) return;
      setCalOut(out);
      if (!opts?.preserveModifiers) setActiveModIds([]);
      setLoggedCalEntry(null);
      setCalLogErr(null);
      calLogIdem.reset();
    } catch (e) {
      if (ctrl.signal.aborted || seq !== calReqSeq.current || (e instanceof Error && e.name === 'AbortError')) return;
      setCalErr(e);
    } finally {
      if (seq === calReqSeq.current) setCalBusy(false);
    }
  };

  const pickMealPhoto = async (camera: boolean) => {
    setCalErr(null);
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 1, allowsMultipleSelection: false };
    if (camera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        setCalErr(new Error('camera'));
        return;
      }
    }
    const res = camera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (res.canceled || !res.assets[0]) return;
    setCalBusy(true);
    try {
      const prepared = await prepareImage(res.assets[0].uri);
      setDishQuery('');
      setSelectedDishSlug(null);
      setMealImg(prepared);
      await estimateMeal({ img: prepared, dishName: '', dishSlug: null });
    } catch (e) {
      setCalErr(e);
      setCalBusy(false);
    }
  };

  const lookupBarcode = async (codeArg?: string) => {
    const code = (codeArg ?? barcode).trim();
    if (!code) return;
    setBarcode(code);
    setBcBusy(true);
    setBcErr(null);
    setBcNote(null);
    try {
      const res = await call(api.GET('/meal-calorie/barcode/{barcode}', { params: { path: { barcode: code } } }));
      setBcOut(res);
      setBcUnit(res.kcal_per_serving != null ? 'serving' : '100g');
      setLoggedBcEntry(null);
    } catch (e) {
      setBcOut(null);
      setBcErr(e);
    } finally {
      setBcBusy(false);
    }
  };

  const scanBarcodePhoto = async (camera: boolean) => {
    setBcErr(null);
    setBcNote(null);
    const DetectorCtor = (
      globalThis as unknown as {
        BarcodeDetector?: new (o?: object) => { detect: (src: unknown) => Promise<{ rawValue?: string }[]> };
      }
    ).BarcodeDetector;
    if (!DetectorCtor || typeof document === 'undefined') {
      setBcNote('Trình duyệt hiện tại chưa hỗ trợ tự đọc mã vạch từ ảnh. Vui lòng nhập trực tiếp dãy số mã vạch bên dưới.');
      return;
    }
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 1, allowsMultipleSelection: false };
    if (camera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        setBcErr(new Error('camera'));
        return;
      }
    }
    const res = camera ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
    if (res.canceled || !res.assets[0]) return;
    setBcBusy(true);
    try {
      const imgEl = new window.Image();
      imgEl.crossOrigin = 'anonymous';
      await new Promise<void>((resolve, reject) => {
        imgEl.onload = () => resolve();
        imgEl.onerror = () => reject(new Error('load'));
        imgEl.src = res.assets[0].uri;
      });
      const det = new DetectorCtor({ formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128'] });
      const found = await det.detect(imgEl);
      const val = found.find((x) => x.rawValue && /^[0-9]{8,14}$/.test(x.rawValue))?.rawValue;
      if (!val) {
        setBcNote('Chưa nhận ra mã vạch rõ nét trong ảnh. Hãy chụp gần hơn hoặc nhập dãy số thủ công.');
        setBcBusy(false);
        return;
      }
      await lookupBarcode(val);
    } catch {
      setBcNote('Không đọc được mã vạch từ ảnh. Vui lòng nhập trực tiếp dãy số mã vạch.');
      setBcBusy(false);
    }
  };

  const plateModifiers = useMemo(() => mergeModifiers(calOut?.suggested_modifiers), [calOut?.suggested_modifiers]);
  const adjustedPlate = useMemo(
    () => (calOut ? applyPlateModifiers(calOut, activeModIds, plateModifiers) : null),
    [calOut, activeModIds, plateModifiers],
  );
  const disambig = useMemo(() => (calOut ? needsDisambiguation(calOut) : { required: false }), [calOut]);
  const provenanceLabel = calOut ? resolveProvenanceLabel(calOut) : '';
  const dailyTarget = profile.data?.kcal_target ?? null;

  const toggleModifier = (modId: string) => {
    setLoggedCalEntry(null);
    setActiveModIds((prev) => (prev.includes(modId) ? prev.filter((id) => id !== modId) : [...prev, modId]));
  };

  const logCalorieToJournal = async () => {
    if (!calOut || !adjustedPlate || calLogBusyRef.current) return;
    calLogBusyRef.current = true;
    setCalLogBusy(true);
    setCalLogErr(null);
    try {
      const portionText = PLATE_PORTIONS.find(([k]) => k === portion)?.[1] ?? 'Vừa 1.0×';
      const payload = {
        meal_slot: calSlot,
        title_vi: calOut.dish_name_vi ?? 'Món ăn quét calo',
        source_kind: 'scan_calorie' as const,
        source_ref_id: calOut.kb_slug ?? calOut.recognized_dish_id ?? null,
        portion_label: portionText,
        portion_scale: calOut.portion_multiplier,
        modifiers_vi: adjustedPlate.activeModifiers.map((m) => `${m.label_vi} (${formatModifierDelta(m.kcal_delta)})`),
        kcal: adjustedPlate.estimated_kcal,
        kcal_low: adjustedPlate.kcal_low,
        kcal_high: adjustedPlate.kcal_high,
        protein_g: adjustedPlate.protein_g,
        carbs_g: adjustedPlate.carbs_g,
        fat_g: adjustedPlate.fat_g,
        fiber_g: adjustedPlate.fiber_g,
        provenance_label_vi: provenanceLabel,
      };
      const entry = await addQuickMealLog(payload, user?.id, calLogIdem.keyFor(payload));
      calLogIdem.reset();
      setLoggedCalEntry(entry);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['quick-logs'] }),
        qc.invalidateQueries({ queryKey: ['journal'] }),
      ]);
    } catch (e) {
      setCalLogErr(e);
    } finally {
      calLogBusyRef.current = false;
      setCalLogBusy(false);
    }
  };

  const undoCalorieLog = async () => {
    if (!loggedCalEntry) return;
    await removeQuickMealLog(loggedCalEntry.id, user?.id);
    setLoggedCalEntry(null);
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['quick-logs'] }),
      qc.invalidateQueries({ queryKey: ['journal'] }),
    ]);
  };

  const logBarcodeToJournal = async () => {
    if (!bcOut || bcLogBusyRef.current) return;
    bcLogBusyRef.current = true;
    setBcLogBusy(true);
    setBcLogErr(null);
    try {
      const active = resolveBarcodeActiveNutrition(bcOut, bcUnit);
      const payload = {
        meal_slot: bcSlot,
        title_vi: bcOut.product_name,
        source_kind: 'barcode' as const,
        source_ref_id: bcOut.barcode,
        portion_label: active.portion_label,
        modifiers_vi: [],
        kcal: active.kcal,
        kcal_low: active.kcal,
        kcal_high: active.kcal,
        protein_g: active.protein_g,
        carbs_g: active.carbs_g,
        fat_g: active.fat_g,
        fiber_g: active.fiber_g,
        provenance_label_vi: bcOut.source ? sanitizeProvenanceText(bcOut.source) : 'Nhãn sản phẩm mã vạch',
      };
      const entry = await addQuickMealLog(payload, user?.id, bcLogIdem.keyFor(payload));
      bcLogIdem.reset();
      setLoggedBcEntry(entry);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['quick-logs'] }),
        qc.invalidateQueries({ queryKey: ['journal'] }),
      ]);
    } catch (e) {
      setBcLogErr(e);
    } finally {
      bcLogBusyRef.current = false;
      setBcLogBusy(false);
    }
  };

  const undoBarcodeLog = async () => {
    if (!loggedBcEntry) return;
    await removeQuickMealLog(loggedBcEntry.id, user?.id);
    setLoggedBcEntry(null);
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['quick-logs'] }),
      qc.invalidateQueries({ queryKey: ['journal'] }),
    ]);
  };

  if (notOpen && section === 'ingredients') {
    return (
      <Screen testID="screen-scan-closed" variant="focused">
        <T v="h1" accessibilityRole="header">
          Quét nguyên liệu
        </T>
        <Notice tone="warn">
          <T v="title">Quét ảnh chưa mở</T>
          <T>Máy chủ này chưa chạy phần nhận diện ảnh. Bạn vẫn thêm được đồ vào kho bằng tay; mâm cơm ghép từ kho như bình thường.</T>
        </Notice>
        <Button label="Thêm đồ bằng tay trong Kho" onPress={() => goTab('/kho')} />
        <Button label="Quay lại" kind="ghost" onPress={() => router.back()} />
      </Screen>
    );
  }

  const calorieInputCol = (
    <View style={{ gap: space.md }}>
      <Row gap={space.sm} style={{ flexWrap: 'nowrap' }}>
        <Button
          label="Chụp ảnh món"
          icon={<Icon name="camera" color={calBusy ? c.muted : c.onAccent} />}
          onPress={() => pickMealPhoto(true)}
          loading={calBusy}
          testID="calorie-camera"
          style={{ flex: 1, paddingHorizontal: space.md }}
        />
        <Button
          label="Chọn ảnh món"
          kind="secondary"
          onPress={() => pickMealPhoto(false)}
          disabled={calBusy}
          testID="calorie-library"
          style={{ flex: 1, paddingHorizontal: space.md }}
        />
      </Row>

      {mealImg ? (
        <Card style={{ padding: space.sm, flexDirection: 'row', gap: space.md, alignItems: 'center' }}>
          <Image source={{ uri: mealImg.uri }} style={{ width: 72, height: 72, borderRadius: radius.sm }} contentFit="cover" />
          <View style={{ flex: 1, gap: space.xs }}>
            <T v="label">Ảnh món ăn đang phân tích</T>
            <Button
              kind="ghost"
              compact
              label="Xoá ảnh"
              testID="calorie-remove-image"
              onPress={() => {
                setMealImg(null);
                const last = lastCalQueryRef.current;
                if (last?.img && !last.dishName && !last.dishSlug) {
                  calAbortRef.current?.abort();
                  setCalOut(null);
                  setActiveModIds([]);
                  setLoggedCalEntry(null);
                  lastCalQueryRef.current = null;
                } else if (last) {
                  lastCalQueryRef.current = { ...last, img: null };
                }
              }}
            />
          </View>
        </Card>
      ) : null}

      <Card style={{ padding: space.lg, gap: space.sm }}>
        <Field
          label="Hoặc tìm nhanh món ăn / mì tôm / đồ uống"
          placeholder="VD: Mì Hảo Hảo, Phở, Cơm tấm, Trà sữa..."
          value={dishQuery}
          onChangeText={(text) => {
            setDishQuery(text);
            setSelectedDishSlug(null);
          }}
          testID="calorie-search-input"
        />
        <Row gap={space.xs}>
          {QUICK_FOOD_QUERIES.map((q) => {
            const active = dishQuery.trim().toLowerCase() === q.toLowerCase();
            return (
              <Pressable
                key={q}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                onPress={() => {
                  setMealImg(null);
                  setDishQuery(q);
                  setSelectedDishSlug(null);
                  void estimateMeal({ img: null, dishName: q, dishSlug: null });
                }}
                style={({ pressed }) => ({
                  minHeight: 36,
                  maxWidth: '100%',
                  flexShrink: 1,
                  paddingHorizontal: space.sm,
                  paddingVertical: 6,
                  borderRadius: radius.sm,
                  borderWidth: 1,
                  borderColor: active ? c.accent : c.hairline,
                  backgroundColor: active ? c.accentSoft : pressed ? c.surfaceAlt : c.surface,
                  justifyContent: 'center',
                })}>
                <T v={active ? 'label' : 'body'} tone={active ? 'accent' : 'text'} style={{ flexShrink: 1 }}>
                  {q}
                </T>
              </Pressable>
            );
          })}
        </Row>
        {matchingDishes.length > 0 ? (
          <View style={{ gap: space.xs, paddingTop: space.xs }}>
            <T v="small" tone="muted">
              Kết quả gợi ý ({matchingDishes.length} món):
            </T>
            <View style={{ borderTopWidth: 1, borderTopColor: c.hairline }}>
              {matchingDishes.map((d) => (
                <Pressable
                  key={d.slug}
                  testID={`calorie-suggestion-${d.slug}`}
                  accessibilityRole="button"
                  onPress={() => {
                    setMealImg(null);
                    setDishQuery(d.name_vi);
                    setSelectedDishSlug(d.slug);
                    void estimateMeal({ img: null, dishName: d.name_vi, dishSlug: d.slug });
                  }}
                  style={({ pressed }) => ({
                    minHeight: 40,
                    paddingVertical: 6,
                    paddingHorizontal: space.xs,
                    borderBottomWidth: 1,
                    borderBottomColor: c.hairline,
                    flexDirection: 'row',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: space.sm,
                    backgroundColor: pressed ? c.surfaceAlt : 'transparent',
                  })}>
                  <T v="body" style={{ flex: 1, minWidth: 0 }}>
                    {d.name_vi}
                  </T>
                  <T v="small" tone="muted" tabular>
                    ~{Math.round(d.kcal_per_serving)} kcal
                  </T>
                </Pressable>
              ))}
            </View>
          </View>
        ) : null}
        <Button
          label="Ước lượng theo tên món"
          kind="secondary"
          compact
          onPress={() => {
            const trimmed = dishQuery.trim();
            if (trimmed) {
              setMealImg(null);
              void estimateMeal({ img: null, dishName: trimmed, dishSlug: selectedDishSlug });
            } else {
              void estimateMeal({ img: mealImg, dishName: '', dishSlug: null });
            }
          }}
          disabled={calBusy || (!dishQuery.trim() && !mealImg)}
          testID="calorie-estimate-btn"
        />
      </Card>
    </View>
  );

  const calorieResultCol = (
    <View style={{ gap: space.md }}>
      {calOut && adjustedPlate ? (
        <Card
          variant="ledger"
          style={{
            padding: space.lg,
            gap: space.md,
            borderTopWidth: 3,
            borderTopColor: c.text,
          }}
          testID="calorie-result-card">
          {/* Header: provenance & Mỹ Vị nutrition index */}
          <View style={{ gap: space.xs, paddingBottom: space.sm, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
            <Row style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap' }} gap={space.xs}>
              <T v="label" tone="accent" style={{ flexShrink: 1 }}>
                {provenanceLabel}
              </T>
              {(calOut.nutrition_grade != null || calOut.nutrition_score != null) ? (
                <View
                  style={{
                    backgroundColor: c[gradeTone(calOut.nutrition_grade).bgKey],
                    paddingHorizontal: space.sm,
                    paddingVertical: 4,
                    borderRadius: radius.sm,
                    maxWidth: '100%',
                    flexShrink: 1,
                  }}>
                  <T v="small" tabular tone={gradeTone(calOut.nutrition_grade).fgKey}>
                    Chỉ số dinh dưỡng Mỹ Vị: {gradeTone(calOut.nutrition_grade).label}
                  </T>
                </View>
              ) : null}
            </Row>

            <T v="h1">{calOut.dish_name_vi ?? 'Món ăn phân tích từ ảnh chụp'}</T>

            <Row gap={space.sm}>
              {calOut.serving_desc_vi ? (
                <T v="small" tone="muted" style={{ flexShrink: 1 }}>
                  Khẩu phần chuẩn: {calOut.serving_desc_vi}
                </T>
              ) : null}
              {calOut.source_ref ? (
                <T v="small" tone="muted" style={{ flexShrink: 1 }}>
                  Nguồn: {sanitizeProvenanceText(calOut.source_ref)}
                </T>
              ) : null}
            </Row>
          </View>

          {/* Top-2 Disambiguation Banner (borderless soft-tinted inline banner) */}
          {disambig.required && disambig.c1 && disambig.c2 ? (
            <View
              testID="calorie-disambiguation-banner"
              style={{
                backgroundColor: c.warnSoft,
                borderWidth: 1,
                borderColor: c.hairline,
                borderRadius: radius.sm,
                padding: space.md,
                gap: space.xs,
              }}>
              <T v="label">
                Ảnh có thể là {disambig.c2.name_vi}. Chạm để đổi nhanh:
              </T>
              <Row gap={space.xs}>
                {[disambig.c1, disambig.c2].map((cand) => {
                  const selected = calOut.recognized_dish_id === cand.dish_id || calOut.dish_name_vi === cand.name_vi;
                  const label = `${cand.name_vi}${cand.kcal_vua != null ? ` (${Math.round(cand.kcal_vua)} kcal)` : ''}`;
                  return (
                    <Pressable
                      key={cand.dish_id}
                      accessibilityRole="button"
                      accessibilityState={{ selected }}
                      onPress={() => {
                        setDishQuery(cand.name_vi);
                        setSelectedDishSlug(cand.kb_slug ?? null);
                        void estimateMeal({ img: mealImg, dishName: cand.name_vi, dishSlug: cand.kb_slug ?? null });
                      }}
                      style={({ pressed }) => ({
                        minHeight: 40,
                        maxWidth: '100%',
                        flexShrink: 1,
                        paddingHorizontal: space.md,
                        paddingVertical: 6,
                        borderRadius: radius.sm,
                        borderWidth: 1,
                        borderColor: selected ? c.accent : c.hairline,
                        backgroundColor: selected ? c.accentSoft : pressed ? c.surfaceAlt : c.surface,
                        justifyContent: 'center',
                      })}>
                      <T v={selected ? 'label' : 'body'} tone={selected ? 'accent' : 'text'} tabular style={{ flexShrink: 1 }}>
                        {label}
                      </T>
                    </Pressable>
                  );
                })}
              </Row>
            </View>
          ) : null}

          {/* Primary Energy Readout & Calibrated [low..high] Range Bar */}
          <View style={{ gap: space.sm }}>
            <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: space.sm }}>
              <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: space.sm, flexWrap: 'wrap' }}>
                <T v="huge" tabular tone="accent">
                  {Math.round(adjustedPlate.estimated_kcal)} kcal
                </T>
                <T v="small" tone="muted" tabular>
                  Ước tính từ {Math.round(adjustedPlate.kcal_low)} đến {Math.round(adjustedPlate.kcal_high)} kcal
                </T>
              </View>
              {adjustedPlate.estimated_mass_g != null ? (
                <T v="small" tone="muted" tabular>
                  Khối lượng ước tính ~{Math.round(adjustedPlate.estimated_mass_g)}g
                </T>
              ) : null}
            </View>

            {(() => {
              const scaleMax = Math.max(adjustedPlate.kcal_high, dailyTarget ? Math.round(dailyTarget * 0.5) : 0, 100) * 1.15;
              const lowPct = Math.min(95, Math.max(0, (adjustedPlate.kcal_low / scaleMax) * 100));
              const highPct = Math.min(100, Math.max(lowPct + 4, (adjustedPlate.kcal_high / scaleMax) * 100));
              const midPct = Math.min(98, Math.max(2, (adjustedPlate.estimated_kcal / scaleMax) * 100));
              const sharePct = dailyTarget ? Math.round((adjustedPlate.estimated_kcal / dailyTarget) * 100) : null;
              return (
                <View testID="calorie-range-bar" style={{ gap: 4 }}>
                  <View
                    style={{ height: 8, borderRadius: radius.sm, backgroundColor: c.surfaceAlt, overflow: 'hidden', position: 'relative' }}
                    accessibilityLabel={`Khoảng ${adjustedPlate.kcal_low} đến ${adjustedPlate.kcal_high} kcal, trung vị ${adjustedPlate.estimated_kcal} kcal`}>
                    <View
                      style={{
                        position: 'absolute',
                        left: `${lowPct}%`,
                        width: `${Math.max(4, highPct - lowPct)}%`,
                        top: 0,
                        bottom: 0,
                        backgroundColor: c.accentSoft,
                        borderRadius: radius.sm,
                      }}
                    />
                    <View
                      style={{
                        position: 'absolute',
                        left: `${midPct}%`,
                        top: 0,
                        bottom: 0,
                        width: 4,
                        marginLeft: -2,
                        backgroundColor: c.accent,
                        borderRadius: radius.sm,
                      }}
                    />
                  </View>
                  <Row style={{ justifyContent: 'space-between' }}>
                    <T v="small" tone="muted" tabular>
                      {adjustedPlate.kcal_low} kcal
                    </T>
                    <T v="small" tone="muted" tabular>
                      {sharePct != null
                        ? `Chiếm ~${sharePct}% mục tiêu ${Math.round(dailyTarget!)} kcal/ngày`
                        : `Biên độ ±${Math.round(Math.max(0, (adjustedPlate.kcal_high - adjustedPlate.kcal_low) / 2))} kcal`}
                    </T>
                    <T v="small" tone="muted" tabular>
                      {adjustedPlate.kcal_high} kcal
                    </T>
                  </Row>
                </View>
              );
            })()}
          </View>

          {/* Inline Staging Plate Portion Multiplier (3-column Hairline Segmented Control) */}
          <HairlineSegmented
            testID="plate-portion-selector"
            label="Chỉnh kích cỡ suất ăn:"
            options={PLATE_PORTIONS}
            value={portion}
            disabled={calBusy}
            onChange={(pVal) => {
              setPortion(pVal);
              const base = lastCalQueryRef.current;
              void estimateMeal({
                img: base ? base.img : mealImg,
                dishName: base ? base.dishName : dishQuery.trim(),
                dishSlug: base ? base.dishSlug : (calOut.kb_slug ?? selectedDishSlug),
                nextPortion: pVal,
                preserveModifiers: true,
              });
            }}
          />

          {/* 1-Tap VN Hidden-Calorie Receipt Checklist Rows */}
          <View testID="plate-modifiers" style={{ gap: space.xs }}>
            <T v="small" tone="muted">
              Điều chỉnh nhanh phần ăn kèm &amp; cách chế biến:
            </T>
            <View>
              {plateModifiers.map((mod, idx) => (
                <ReceiptCheckRow
                  key={mod.id}
                  testID={`modifier-${mod.id}`}
                  first={idx === 0}
                  checked={activeModIds.includes(mod.id)}
                  label={mod.label_vi}
                  rightText={formatModifierDelta(mod.kcal_delta)}
                  onPress={() => toggleModifier(mod.id)}
                />
              ))}
            </View>
          </View>

          {/* Pure-SVG Macro Pie/Donut Chart + Expanded Nutrition Facts Ledger */}
          <MacroPieLedger
            proteinG={adjustedPlate.protein_g}
            carbsG={adjustedPlate.carbs_g}
            fatG={adjustedPlate.fat_g}
            fiberG={adjustedPlate.fiber_g}
            totalKcal={adjustedPlate.estimated_kcal}
            massG={adjustedPlate.estimated_mass_g}
            nutritionGrade={calOut.nutrition_grade}
            context="meal"
          />

          {calOut.top_candidates && calOut.top_candidates.length > 0 && !disambig.required ? (
            <View style={{ gap: space.xs }}>
              <T v="small" tone="muted">
                Các món tương đồng gợi ý (chạm để chuyển nhanh):
              </T>
              <Row gap={space.xs}>
                {calOut.top_candidates.map((cand) => {
                  const selected = calOut.recognized_dish_id === cand.dish_id;
                  return (
                    <Pressable
                      key={cand.dish_id}
                      accessibilityRole="button"
                      accessibilityState={{ selected }}
                      onPress={() => {
                        setDishQuery(cand.name_vi);
                        setSelectedDishSlug(cand.kb_slug ?? null);
                        void estimateMeal({ img: mealImg, dishName: cand.name_vi, dishSlug: cand.kb_slug ?? null });
                      }}
                      style={({ pressed }) => ({
                        minHeight: 38,
                        maxWidth: '100%',
                        flexShrink: 1,
                        paddingHorizontal: space.sm,
                        paddingVertical: 6,
                        borderRadius: radius.sm,
                        borderWidth: 1,
                        borderColor: selected ? c.accent : c.hairline,
                        backgroundColor: selected ? c.accentSoft : pressed ? c.surfaceAlt : c.surface,
                        justifyContent: 'center',
                      })}>
                      <T v={selected ? 'label' : 'body'} tone={selected ? 'accent' : 'text'} tabular style={{ flexShrink: 1 }}>
                        {`${cand.name_vi}${cand.kcal_vua != null ? ` (${Math.round(cand.kcal_vua)} kcal)` : ''}`}
                      </T>
                    </Pressable>
                  );
                })}
              </Row>
            </View>
          ) : null}

          {calOut.domain_shift_note ? (
            <View
              style={{
                backgroundColor: calOut.ood_clamped ? c.warnSoft : c.surfaceAlt,
                borderRadius: radius.sm,
                padding: space.md,
              }}>
              <T v="small">{sanitizeProvenanceText(calOut.domain_shift_note)}</T>
            </View>
          ) : null}

          {/* 1-Tap Meal Slot + Ghi vào Nhật ký hôm nay */}
          <View style={{ borderTopWidth: 1, borderTopColor: c.hairline, paddingTop: space.md, gap: space.sm }}>
            <HairlineSegmented
              label="Lưu vào bữa:"
              options={MEAL_SLOTS.map((s) => [s, MEAL_SLOT_LABEL[s]] as const)}
              value={calSlot}
              onChange={setCalSlot}
            />
            <Button
              label="Ghi vào Nhật ký hôm nay"
              testID="calorie-log-to-journal"
              icon={<Icon name="check" size={18} color={calLogBusy ? c.muted : c.onAccent} />}
              disabled={calLogBusy}
              loading={calLogBusy}
              onPress={() => void logCalorieToJournal()}
            />
            {calLogErr ? <ErrorBox message={errorText(calLogErr)} /> : null}
            {loggedCalEntry ? (
              <View
                testID="calorie-logged-notice"
                style={{ backgroundColor: c.okSoft, borderRadius: radius.md, padding: space.md, gap: space.xs }}>
                <T v="label">
                  Đã ghi {loggedCalEntry.title_vi} ({loggedCalEntry.kcal} kcal, bữa {MEAL_SLOT_LABEL[loggedCalEntry.meal_slot]}) vào Nhật ký hôm nay.
                </T>
                <Row gap={space.xs}>
                  <Button label="Xem Nhật ký" kind="secondary" compact onPress={() => goTab('/nhat-ky')} />
                  <Button label="Hoàn tác" kind="ghost" compact onPress={() => void undoCalorieLog()} />
                </Row>
              </View>
            ) : null}
          </View>
        </Card>
      ) : isDesktop && !calErr ? (
        <Card style={{ padding: space.xl, gap: space.sm, backgroundColor: c.surfaceAlt }}>
          <T v="h2" accessibilityRole="header">
            Chụp bữa ăn hoặc chọn món
          </T>
          <T tone="muted">
            Chụp bữa ăn hoặc chọn nhanh một món ở cột bên trái để xem dinh dưỡng bữa ăn, chỉnh suất Nhỏ, Vừa, Lớn, thêm gia vị kèm rồi lưu vào Nhật ký.
          </T>
        </Card>
      ) : null}

      {calErr instanceof Error && calErr.message === 'camera' ? (
        <ErrorBox message="Chưa có quyền dùng máy ảnh. Chọn ảnh có sẵn hoặc tìm tên món bên trên." />
      ) : calErr ? (
        <ErrorBox message={errorText(calErr)} />
      ) : null}
    </View>
  );

  return (
    <Screen
      testID="screen-scan"
      variant={section === 'calorie' && isDesktop ? 'workspace' : 'focused'}
      footer={
        section === 'ingredients' ? (
          <Button label="Gửi ảnh để nhận diện" testID="scan-send" onPress={send} loading={busy} disabled={!images.length} />
        ) : undefined
      }>
      <View style={{ gap: 2 }}>
        <T v="huge" accessibilityRole="header">
          {section === 'ingredients' ? 'Quét nguyên liệu' : section === 'calorie' ? 'Xem dinh dưỡng bữa ăn' : 'Quét mã vạch'}
        </T>
        <T tone="muted">
          {section === 'ingredients'
            ? mode === 'fridge'
              ? 'Mở cửa tủ lạnh, chụp thẳng từng ngăn đủ ánh sáng (tối đa 2 ảnh).'
              : 'Bày đồ vừa mua ra bàn, không chồng lên nhau. Ngày mua sẽ tự động ghi là hôm nay.'
            : section === 'calorie'
              ? 'Chụp bữa ăn hoặc tìm tên món để xem dinh dưỡng bữa ăn và điều chỉnh khẩu phần.'
              : 'Tra cứu calo và thành phần dinh dưỡng của mì gói, sữa, bánh kẹo theo mã vạch.'}
        </T>
      </View>

      <UnderlineTabs
        label="Chế độ quét"
        options={[
          ['ingredients', 'Nguyên liệu'],
          ['calorie', 'Món ăn & Calo'],
          ['barcode', 'Mã vạch'],
        ]}
        value={section}
        onChange={setSection}
      />

      {section === 'ingredients' ? (
        <>
          <Segmented options={[['fridge', 'Toàn tủ lạnh'], ['haul', 'Đồ vừa mua']]} value={mode} onChange={setMode} />

          {images.length > 0 ? (
            <Row gap={space.md}>
              {images.map((img, i) => (
                <Card key={img.uri} style={{ padding: space.sm, gap: space.xs }}>
                  <Image
                    source={{ uri: img.uri }}
                    style={{ width: 164, height: 164, borderRadius: radius.sm, backgroundColor: c.surfaceAlt }}
                    contentFit="cover"
                    accessibilityLabel={`Ảnh ${i + 1}`}
                  />
                  <Button
                    kind="ghost"
                    label="Bỏ ảnh"
                    icon={<Icon name="trash" size={16} color={c.accent} />}
                    onPress={() => setImages((s) => s.filter((x) => x !== img))}
                  />
                </Card>
              ))}
            </Row>
          ) : (
            <Card style={{ backgroundColor: c.surface, padding: space.xl, gap: space.md }}>
              <View
                style={{
                  width: 52,
                  height: 52,
                  borderRadius: radius.md,
                  backgroundColor: c.accentSoft,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                <Icon name="camera" size={24} color={c.accent} />
              </View>
              <View style={{ gap: 4 }}>
                <T v="title">Mẹo chụp ảnh nhận diện chính xác</T>
                <T tone="muted">
                  1. Đặt thực phẩm rõ mặt trước, hạn chế túi nilon mờ đục.{'\n'}
                  2. Giữ máy ảnh song song với ngăn tủ hoặc mặt bàn.{'\n'}
                  3. Sau khi quét, bạn luôn có thể chạm vào khung vùng chọn để sửa tên hoặc số lượng.
                </T>
              </View>
            </Card>
          )}

          {images.length < 2 ? (
            <View style={{ gap: space.sm }}>
              <Button
                label="Chụp ảnh"
                icon={<Icon name="camera" color={busy ? c.muted : c.onAccent} />}
                onPress={() => add(true)}
                disabled={busy}
                testID="scan-camera"
              />
              <Button label="Chọn ảnh có sẵn" kind="secondary" onPress={() => add(false)} disabled={busy} testID="scan-library" />
            </View>
          ) : null}

          {photoConsent ? (
            <Checkbox
              checked={contribute}
              onChange={setContribute}
              label="Góp ảnh ẩn danh giúp cải thiện độ chính xác"
              sub={<T v="small" tone="muted">Không tích: ảnh gốc bị xoá sau 30 ngày.</T>}
            />
          ) : (
            <T v="small" tone="muted">
              Ảnh gốc bị xoá sau 30 ngày theo chính sách lưu trữ.
            </T>
          )}
          {err instanceof Error && err.message === 'camera' ? (
            <ErrorBox message="Chưa có quyền dùng máy ảnh. Bật trong cài đặt của máy, hoặc chọn ảnh có sẵn." />
          ) : err ? (
            <ErrorBox message={errorText(err)} />
          ) : null}
        </>
      ) : null}

      {section === 'calorie' ? (
        <View style={{ gap: space.md }} testID="scan-calorie-panel">
          {isDesktop ? (
            <View style={{ flexDirection: 'row', gap: space.xl, alignItems: 'flex-start' }}>
              <View style={{ flex: 5, minWidth: 0 }}>{calorieInputCol}</View>
              <View style={{ flex: 7, minWidth: 0 }}>{calorieResultCol}</View>
            </View>
          ) : (
            <>
              {calorieInputCol}
              {calorieResultCol}
            </>
          )}
        </View>
      ) : null}

      {section === 'barcode' ? (
        <View style={{ gap: space.md }} testID="scan-barcode-panel">
          <Card style={{ padding: space.lg, gap: space.sm }}>
            <Field
              label="Mã vạch sản phẩm (8 đến 14 số)"
              placeholder="VD: 8934563138165"
              value={barcode}
              onChangeText={setBarcode}
              keyboardType="numeric"
              testID="barcode-input"
            />
            <Row gap={space.sm}>
              <Button
                label="Tra cứu mã vạch"
                icon={<Icon name="search" color={bcBusy ? c.muted : c.onAccent} />}
                onPress={() => lookupBarcode()}
                loading={bcBusy}
                disabled={!/^[0-9]{8,14}$/.test(barcode.trim())}
                testID="barcode-lookup-btn"
              />
              <Button
                label="Quét ảnh mã vạch"
                kind="secondary"
                icon={<Icon name="camera" color={c.text} />}
                onPress={() => scanBarcodePhoto(false)}
                disabled={bcBusy}
                testID="barcode-photo-btn"
              />
            </Row>
            <View style={{ gap: space.xs, paddingTop: space.xs }}>
              <T v="small" tone="muted">
                Thử nhanh sản phẩm Việt phổ biến:
              </T>
              <Row gap={space.xs}>
                {QUICK_BARCODES.map(([code, title]) => {
                  const active = barcode.trim() === code;
                  return (
                    <Pressable
                      key={code}
                      accessibilityRole="button"
                      accessibilityState={{ selected: active }}
                      onPress={() => void lookupBarcode(code)}
                      style={({ pressed }) => ({
                        minHeight: 36,
                        maxWidth: '100%',
                        flexShrink: 1,
                        paddingHorizontal: space.sm,
                        paddingVertical: 6,
                        borderRadius: radius.sm,
                        borderWidth: 1,
                        borderColor: active ? c.accent : c.hairline,
                        backgroundColor: active ? c.accentSoft : pressed ? c.surfaceAlt : c.surface,
                        justifyContent: 'center',
                      })}>
                      <T v={active ? 'label' : 'body'} tone={active ? 'accent' : 'text'} tabular style={{ flexShrink: 1 }}>
                        {`${title} (${code})`}
                      </T>
                    </Pressable>
                  );
                })}
              </Row>
            </View>
          </Card>

          {bcNote ? (
            <Notice tone="info">
              <T v="small">{bcNote}</T>
            </Notice>
          ) : null}

          {bcOut ? (
            <Card
              variant="ledger"
              style={{
                padding: space.lg,
                gap: space.md,
                borderTopWidth: 3,
                borderTopColor: c.text,
              }}
              testID="barcode-result-card">
              <Row style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap' }} gap={space.xs}>
                <T v="label" tone="accent" style={{ flexShrink: 1 }}>
                  {sanitizeProvenanceText(bcOut.source)}{bcOut.brand ? `, ${bcOut.brand}` : ''}
                </T>
                {(bcOut.nutrition_grade != null || bcOut.nutrition_score != null) ? (
                  <View
                    style={{
                      backgroundColor: c[gradeTone(bcOut.nutrition_grade).bgKey],
                      paddingHorizontal: space.sm,
                      paddingVertical: 4,
                      borderRadius: radius.sm,
                      maxWidth: '100%',
                      flexShrink: 1,
                    }}>
                    <T v="small" tabular tone={gradeTone(bcOut.nutrition_grade).fgKey}>
                      Chỉ số dinh dưỡng Mỹ Vị: {gradeTone(bcOut.nutrition_grade).label}
                    </T>
                  </View>
                ) : null}
              </Row>
              <T v="h1">{bcOut.product_name}</T>
              {bcOut.serving_size ? (
                <T v="small" tone="muted">
                  Khẩu phần nhãn: {bcOut.serving_size}
                </T>
              ) : null}

              {bcOut.kcal_per_serving != null && bcOut.kcal_per_100g != null ? (
                <HairlineSegmented
                  testID="barcode-unit-toggle"
                  options={[
                    ['serving', 'Theo 1 phần'],
                    ['100g', 'Theo 100g'],
                  ]}
                  value={bcUnit}
                  onChange={setBcUnit}
                />
              ) : null}

              {(() => {
                const active = resolveBarcodeActiveNutrition(bcOut, bcUnit);
                if (!active.hasKcal) return null;
                return (
                  <View style={{ gap: space.md }}>
                    <T v="huge" tabular tone="accent">
                      {active.kcal} kcal / {active.use100g ? '100g' : 'phần'}
                    </T>
                    <MacroPieLedger
                      proteinG={active.protein_g}
                      carbsG={active.carbs_g}
                      fatG={active.fat_g}
                      fiberG={active.fiber_g}
                      totalKcal={active.kcal}
                      massG={active.mass_g}
                      nutritionGrade={bcOut.nutrition_grade}
                      context="snack"
                    />
                  </View>
                );
              })()}

              {bcOut.kcal_per_100g != null ? (
                <T v="small" tone="muted" tabular>
                  Quy đổi trên 100g: {Math.round(bcOut.kcal_per_100g)} kcal, Đạm {bcOut.protein_g_per_100g ?? 0}g, Tinh bột {bcOut.carbs_g_per_100g ?? 0}g, Béo {bcOut.fat_g_per_100g ?? 0}g
                </T>
              ) : null}

              <View style={{ borderTopWidth: 1, borderTopColor: c.hairline, paddingTop: space.md, gap: space.sm }}>
                <HairlineSegmented
                  label="Lưu vào bữa:"
                  options={MEAL_SLOTS.map((s) => [s, MEAL_SLOT_LABEL[s]] as const)}
                  value={bcSlot}
                  onChange={setBcSlot}
                />
                <Button
                  label="Ghi vào Nhật ký hôm nay"
                  testID="barcode-log-to-journal"
                  icon={<Icon name="check" size={18} color={bcLogBusy ? c.muted : c.onAccent} />}
                  disabled={bcLogBusy}
                  loading={bcLogBusy}
                  onPress={() => void logBarcodeToJournal()}
                />
                {bcLogErr ? <ErrorBox message={errorText(bcLogErr)} /> : null}
                {loggedBcEntry ? (
                  <View
                    testID="barcode-logged-notice"
                    style={{ backgroundColor: c.okSoft, borderRadius: radius.md, padding: space.md, gap: space.xs }}>
                    <T v="label">
                      Đã ghi {loggedBcEntry.title_vi} ({loggedBcEntry.kcal} kcal, bữa {MEAL_SLOT_LABEL[loggedBcEntry.meal_slot]}) vào Nhật ký hôm nay.
                    </T>
                    <Row gap={space.xs}>
                      <Button label="Xem Nhật ký" kind="secondary" compact onPress={() => goTab('/nhat-ky')} />
                      <Button label="Hoàn tác" kind="ghost" compact onPress={() => void undoBarcodeLog()} />
                    </Row>
                  </View>
                ) : null}
              </View>
            </Card>
          ) : null}

          {bcErr instanceof Error && bcErr.message === 'camera' ? (
            <ErrorBox message="Chưa có quyền dùng máy ảnh. Vui lòng nhập trực tiếp mã vạch." />
          ) : bcErr ? (
            <ErrorBox message={errorText(bcErr)} />
          ) : null}
        </View>
      ) : null}
    </Screen>
  );
}
