"""meal_calorie public interface (M17): decoupled dish recognition & calorie estimation."""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.meal_calorie.barcode import BarcodeCatalog, BarcodeUpstreamError
from tastoria.modules.meal_calorie.barcode_decode import decode_barcode_from_image
from tastoria.modules.meal_calorie.dish_classifier import (
    DishClassification,
    DishClassifier,
    load_dish_classifier,
    load_open_vocab_index,
)
from tastoria.modules.meal_calorie.estimator import (
    DEFAULT_DOMAIN_SHIFT_NOTE,
    MAX_CARB_G,
    MAX_FAT_G,
    MAX_KCAL,
    MAX_MASS_G,
    MAX_PROTEIN_G,
    OOD_WARNING_NOTE,
    VISUAL_HALF_WIDTH_REL,
    ArtifactIntegrityError,
    MealCalorieEstimator,
    VisualPrediction,
    load_meal_calorie_estimator,
    sanitize_meal_image,
)
from tastoria.modules.meal_calorie.kb_lookup import PORTION_MULTIPLIERS, KBDishCatalog
from tastoria.modules.meal_calorie.plate_detector import PlateDetector, load_plate_detector
from tastoria.modules.meal_calorie.schemas import (
    BarcodeNutritionOut,
    DetectedPlateOut,
    DishCandidateOut,
    FusionMode,
    MacroKcalSplitOut,
    MealCalorieDishListOut,
    MealCalorieDishOut,
    MealCalorieEstimateOut,
    ModifierSuggestionOut,
    NutritionGrade,
    PortionSize,
)

log = logging.getLogger("tastoria.meal_calorie")


def _finite_nonneg(val: float | None) -> float:
    if val is None:
        return 0.0
    x = float(val)
    return x if (math.isfinite(x) and x > 0.0) else 0.0


def _compute_nutrition_intelligence(
    *,
    kcal: float | None,
    protein_g: float | None,
    carbs_g: float | None,
    fat_g: float | None,
    fiber_g: float | None,
    slot: str | None = None,
    is_packaged: bool = False,
) -> tuple[int, NutritionGrade, MacroKcalSplitOut]:
    """Compute 0-100 Nutritional Balance Score, A-D Grade, and Macro % Energy Split."""
    p = _finite_nonneg(protein_g)
    c = _finite_nonneg(carbs_g)
    f = _finite_nonneg(fat_g)
    fib = _finite_nonneg(fiber_g)

    p_kcal = 4.0 * p
    c_kcal = 4.0 * c
    f_kcal = 9.0 * f
    tot_macro_kcal = p_kcal + c_kcal + f_kcal
    kcal_val = _finite_nonneg(kcal) if kcal is not None else tot_macro_kcal
    k = max(1.0, kcal_val)

    if tot_macro_kcal <= 0.0:
        p_pct = 0
        c_pct = 0
        f_pct = 0
    else:
        p_pct = int(round(100.0 * p_kcal / tot_macro_kcal))
        c_pct = int(round(100.0 * c_kcal / tot_macro_kcal))
        f_pct = max(0, 100 - p_pct - c_pct)

    # Base score 62; reward protein density (up to +18), fiber density (up to +16), balanced calories
    prot_per_100kcal = (p / k) * 100.0
    fib_per_100kcal = (fib / k) * 100.0
    score = 62.0
    score += min(18.0, prot_per_100kcal * 2.2)
    score += min(16.0, fib_per_100kcal * 10.0)
    if slot in ("rau", "canh"):
        score += 8.0
    if tot_macro_kcal > 0.0:
        if f_pct > 45:
            score -= min(18.0, (f_pct - 45) * 0.6)
        if is_packaged and fib < 2.0 and f_pct >= 32:
            score -= 12.0
    if k > 650.0:
        score -= min(12.0, (k - 650.0) / 40.0)

    final_score = int(round(min(98.0, max(25.0, score))))
    grade: NutritionGrade = (
        "A" if final_score >= 80 else "B" if final_score >= 65 else "C" if final_score >= 48 else "D"
    )
    return final_score, grade, MacroKcalSplitOut(protein_pct=p_pct, carbs_pct=c_pct, fat_pct=f_pct)


def _default_repo_root() -> Path:
    # backend/src/tastoria/modules/meal_calorie/service.py -> repo root is 5 parents up
    return Path(__file__).resolve().parents[5]


@dataclass(frozen=True)
class DeployedOnnxRef:
    """Inversion-safe reference to an MLOps-deployed ONNX model (populated by tastoria.app)."""

    version_id: uuid.UUID
    version: str
    serving: dict[str, Any]
    loader: Callable[[], Any]


OnnxProbe = Callable[[uuid.UUID | None], tuple[bool, DeployedOnnxRef | None]]


@dataclass
class MealCalorieDeps:
    """Installed by tastoria.app on app.state.meal_calorie."""

    model_dir: Path
    kb_dir: Path
    kb_processed_dir: Path
    dish_classifier_model_dir: Path | None = None
    plate_detector_model_dir: Path | None = None
    estimator: MealCalorieEstimator | None = None
    dish_classifier: DishClassifier | None = None
    plate_detector: PlateDetector | None = None
    kb_catalog: KBDishCatalog | None = None
    barcode_catalog: BarcodeCatalog | None = None
    estimator_probe: OnnxProbe | None = None
    dish_classifier_probe: OnnxProbe | None = None
    _estimator_version_id: uuid.UUID | None = field(default=None, init=False, repr=False)
    _dish_classifier_version_id: uuid.UUID | None = field(default=None, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    @classmethod
    def from_paths(
        cls,
        *,
        model_dir: str | Path | None = None,
        dish_classifier_model_dir: str | Path | None = None,
        plate_detector_model_dir: str | Path | None = None,
        kb_dir: str | Path | None = None,
        kb_processed_dir: str | Path | None = None,
        preload: bool = False,
        estimator_probe: OnnxProbe | None = None,
        dish_classifier_probe: OnnxProbe | None = None,
    ) -> MealCalorieDeps:
        root = _default_repo_root()
        resolved_model = Path(model_dir) if model_dir else root / "deploy" / "models" / "meal_calorie"
        default_cls = resolved_model.parent / "dish_classifier"
        resolved_cls = (
            Path(dish_classifier_model_dir)
            if dish_classifier_model_dir
            else (default_cls if (default_cls / "serving.json").exists() else None)
        )
        default_plate = resolved_model.parent / "plate_detector"
        resolved_plate = (
            Path(plate_detector_model_dir)
            if plate_detector_model_dir
            else (default_plate if (default_plate / "serving.json").exists() else None)
        )
        resolved_kb = Path(kb_dir) if kb_dir else root / "data" / "kb"
        resolved_proc = Path(kb_processed_dir) if kb_processed_dir else root / "data" / "processed" / "kb"
        deps = cls(
            model_dir=resolved_model,
            dish_classifier_model_dir=resolved_cls,
            plate_detector_model_dir=resolved_plate,
            kb_dir=resolved_kb,
            kb_processed_dir=resolved_proc,
            estimator_probe=estimator_probe,
            dish_classifier_probe=dish_classifier_probe,
        )
        if preload:
            deps.get_kb()
            deps.get_estimator(required=False)
            deps.get_dish_classifier(required=False)
            deps.get_plate_detector()
            deps.get_barcode_catalog()
        return deps

    def get_kb(self) -> KBDishCatalog | None:
        if self.kb_catalog is not None:
            return self.kb_catalog
        with self._lock:
            if self.kb_catalog is not None:
                return self.kb_catalog
            try:
                self.kb_catalog = KBDishCatalog.from_dirs(self.kb_dir, self.kb_processed_dir)
            except FileNotFoundError as exc:
                log.warning("meal_calorie KB lookup unavailable: %s", exc)
                return None
            return self.kb_catalog

    def get_estimator(self, *, required: bool = True) -> MealCalorieEstimator | None:
        with self._lock:
            if self.estimator_probe is not None:
                changed, ref = self.estimator_probe(self._estimator_version_id)
                if changed:
                    if ref is None:
                        self.estimator = None
                        self._estimator_version_id = None
                    else:
                        try:
                            sess = ref.loader()
                            self.estimator = MealCalorieEstimator(sess, serving=ref.serving)
                            self._estimator_version_id = ref.version_id
                            return self.estimator
                        except Exception as exc:  # noqa: BLE001 — integrity/load error fails closed
                            self.estimator = None
                            self._estimator_version_id = None
                            log.error("meal_calorie MLOps ONNX load failed: %s", exc)
                            if required:
                                raise ApiError(503, ProblemCode.model_unavailable, str(exc)) from exc
                            return None
            if self.estimator is not None:
                return self.estimator
            try:
                self.estimator = load_meal_calorie_estimator(self.model_dir, verify_sha256=True)
            except ArtifactIntegrityError as exc:
                log.error("meal_calorie ONNX load failed: %s", exc)
                if required:
                    raise ApiError(503, ProblemCode.model_unavailable, str(exc)) from exc
                return None
            return self.estimator

    def get_dish_classifier(self, *, required: bool = False) -> DishClassifier | None:
        with self._lock:
            if self.dish_classifier_probe is not None:
                changed, ref = self.dish_classifier_probe(self._dish_classifier_version_id)
                if changed:
                    if ref is None:
                        self.dish_classifier = None
                        self._dish_classifier_version_id = None
                    else:
                        try:
                            sess = ref.loader()
                            open_emb, open_meta = (
                                load_open_vocab_index(self.dish_classifier_model_dir)
                                if self.dish_classifier_model_dir is not None
                                else (None, None)
                            )
                            self.dish_classifier = DishClassifier(
                                sess,
                                serving=ref.serving,
                                open_vocab_embeddings=open_emb,
                                open_vocab_meta=open_meta,
                            )
                            self._dish_classifier_version_id = ref.version_id
                            return self.dish_classifier
                        except Exception as exc:  # noqa: BLE001
                            self.dish_classifier = None
                            self._dish_classifier_version_id = None
                            log.warning("dish_classifier MLOps ONNX unavailable: %s", exc)
                            if required:
                                raise ApiError(503, ProblemCode.model_unavailable, str(exc)) from exc
                            return None
            if self.dish_classifier is not None:
                return self.dish_classifier
            if self.dish_classifier_model_dir is None:
                return None
            try:
                self.dish_classifier = load_dish_classifier(self.dish_classifier_model_dir, verify_sha256=True)
            except ArtifactIntegrityError as exc:
                log.warning("dish_classifier ONNX unavailable: %s", exc)
                if required:
                    raise ApiError(503, ProblemCode.model_unavailable, str(exc)) from exc
                return None
            return self.dish_classifier

    def get_plate_detector(self) -> PlateDetector | None:
        with self._lock:
            if self.plate_detector is not None:
                return self.plate_detector
            if self.plate_detector_model_dir is None:
                return None
            try:
                self.plate_detector = load_plate_detector(self.plate_detector_model_dir, verify_sha256=True)
            except (ArtifactIntegrityError, Exception) as exc:  # noqa: BLE001
                log.warning("plate_detector ONNX unavailable: %s", exc)
                return None
            return self.plate_detector

    def get_barcode_catalog(self) -> BarcodeCatalog:
        with self._lock:
            if self.barcode_catalog is None:
                self.barcode_catalog = BarcodeCatalog.from_kb_dir(self.kb_dir)
            else:
                self.barcode_catalog.reopen()
            return self.barcode_catalog

    def close(self) -> None:
        with self._lock:
            if self.barcode_catalog is not None:
                self.barcode_catalog.close()


def list_dishes(deps: MealCalorieDeps, *, include_extended: bool = False) -> MealCalorieDishListOut:
    kb = deps.get_kb()
    if kb is None:
        raise ApiError(503, ProblemCode.service_unavailable, "Chưa có dữ liệu dinh dưỡng KB.")
    items = [
        MealCalorieDishOut(
            slug=d.slug,
            name_vi=d.name_vi,
            slot=d.slot,  # type: ignore[arg-type]
            kcal_per_serving=d.kcal_per_serving,
            protein_g=d.protein_g,
            carbs_g=d.glucid_g,
            fat_g=d.lipid_g,
            fiber_g=d.fiber_g,
        )
        for d in kb.dishes
    ]
    if include_extended:
        seen_slugs = {d.slug for d in kb.dishes}
        for rec in kb.recognized:
            if rec.kb_slug and rec.kb_slug in seen_slugs:
                continue
            slot_val = rec.slot if rec.slot in ("man", "rau", "canh") else "man"
            items.append(
                MealCalorieDishOut(
                    slug=rec.dish_id,
                    name_vi=rec.name_vi,
                    slot=slot_val,  # type: ignore[arg-type]
                    kcal_per_serving=rec.kcal_per_serving,
                    protein_g=rec.protein_g,
                    carbs_g=rec.glucid_g,
                    fat_g=rec.lipid_g,
                    fiber_g=rec.fiber_g,
                )
            )
    return MealCalorieDishListOut(
        data_version=kb.data_version,
        calibrated=kb.calibrated,
        half_width_rel=round(kb.half_width_rel, 4),
        dishes=items,
    )


def lookup_barcode(deps: MealCalorieDeps, *, barcode: str, allow_remote: bool = True) -> BarcodeNutritionOut:
    cat = deps.get_barcode_catalog()
    try:
        item = cat.lookup(barcode, allow_remote=allow_remote, raise_on_transient=True)
    except BarcodeUpstreamError as exc:
        raise ApiError(
            503,
            ProblemCode.temporarily_unavailable,
            "Dịch vụ tra cứu mã vạch tạm thời gián đoạn, vui lòng thử lại sau.",
            headers={"Retry-After": "5"},
        ) from exc
    except ValueError as exc:
        raise ApiError(422, ProblemCode.validation_error, str(exc)) from exc
    if item is None:
        raise ApiError(404, ProblemCode.not_found, f"Không tìm thấy dữ liệu dinh dưỡng cho mã vạch {barcode!r}.")
    has_serving_macros = any(
        v is not None for v in (item.protein_g_per_serving, item.carbs_g_per_serving, item.fat_g_per_serving)
    )
    use_serving = item.kcal_per_serving is not None and (has_serving_macros or item.kcal_per_100g is None)
    if use_serving:
        k_val = item.kcal_per_serving
        p_val = item.protein_g_per_serving
        c_val = item.carbs_g_per_serving
        f_val = item.fat_g_per_serving
        fib_val = item.fiber_g_per_serving
    else:
        k_val = item.kcal_per_100g if item.kcal_per_100g is not None else item.kcal_per_serving
        p_val = item.protein_g_per_100g
        c_val = item.carbs_g_per_100g
        f_val = item.fat_g_per_100g
        fib_val = item.fiber_g_per_100g
    score, grade, split = _compute_nutrition_intelligence(
        kcal=k_val,
        protein_g=p_val,
        carbs_g=c_val,
        fat_g=f_val,
        fiber_g=fib_val,
        is_packaged=True,
    )
    return BarcodeNutritionOut(
        barcode=item.barcode,
        product_name=item.product_name,
        brand=item.brand,
        serving_size=item.serving_size,
        serving_g=item.serving_g,
        kcal_per_serving=item.kcal_per_serving,
        protein_g_per_serving=item.protein_g_per_serving,
        carbs_g_per_serving=item.carbs_g_per_serving,
        fat_g_per_serving=item.fat_g_per_serving,
        fiber_g_per_serving=item.fiber_g_per_serving,
        kcal_per_100g=item.kcal_per_100g,
        protein_g_per_100g=item.protein_g_per_100g,
        carbs_g_per_100g=item.carbs_g_per_100g,
        fat_g_per_100g=item.fat_g_per_100g,
        fiber_g_per_100g=item.fiber_g_per_100g,
        source=item.source,
        image_url=item.image_url,
        nutrition_score=score,
        nutrition_grade=grade,
        macro_kcal_split=split,
    )


def lookup_barcode_image(
    deps: MealCalorieDeps,
    *,
    image_bytes: bytes,
    allow_remote: bool = True,
) -> BarcodeNutritionOut:
    """Decode an EAN-13/EAN-8/UPC-A barcode from image bytes and resolve its product nutrition."""
    if not image_bytes:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            "Chưa có ảnh mã vạch để đọc.",
            errors=[{"pointer": "/image", "code": "required", "message": "thiếu ảnh"}],
        )
    code = decode_barcode_from_image(image_bytes)
    if code is None:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            "Chưa đọc được mã vạch rõ nét trong ảnh. Hãy chụp gần hơn, thẳng góc hoặc nhập tay dãy số.",
            errors=[{"pointer": "/image", "code": "barcode_not_detected", "message": "không nhận ra mã vạch"}],
        )
    try:
        return lookup_barcode(deps, barcode=code, allow_remote=allow_remote)
    except ApiError as exc:
        if exc.status == 404 and len(code) == 13 and code.startswith("0"):
            return lookup_barcode(deps, barcode=code[1:], allow_remote=allow_remote)
        raise


def _provenance_label_vi(source_ref: str | None, *, with_image: bool) -> str:
    ref = (source_ref or "").upper()
    if "NIN" in ref or "FCT 2007" in ref:
        base = "Viện Dinh Dưỡng VN"
    elif "USDA" in ref:
        base = "Bảng thực phẩm USDA"
    elif "LABEL" in ref or "NHÃN" in ref:
        base = "Nhãn sản phẩm & Viện Dinh Dưỡng VN"
    elif "JAPANESE" in ref:
        base = "Bảng thực phẩm Nhật Bản"
    else:
        base = "Bảng món ăn Mỹ Vị"
    return f"{base} & Ảnh" if with_image else base


def _suggest_modifiers(slot: str | None, dish_id: str | None, name_vi: str | None) -> list[ModifierSuggestionOut]:
    did = (dish_id or "").lower()
    nm = (name_vi or "").lower()
    if slot == "canh" or any(k in did or k in nm for k in ("canh", "sup", "súp", "lau", "lẩu")):
        return [
            ModifierSuggestionOut(id="giam_dau", label_vi="Ít dầu / vớt váng mỡ", kcal_delta=-36.0, fat_delta_g=-4.0),
            ModifierSuggestionOut(
                id="them_thit_tom", label_vi="Thêm thịt nạc / tôm", kcal_delta=55.0, protein_delta_g=8.0, fat_delta_g=2.0
            ),
            ModifierSuggestionOut(
                id="them_rau", label_vi="Thêm rau xanh", kcal_delta=15.0, protein_delta_g=1.0, carbs_delta_g=2.5
            ),
        ]
    if slot == "rau" or any(k in did or k in nm for k in ("rau", "salad", "nom", "nộm", "goi", "gỏi")):
        return [
            ModifierSuggestionOut(id="them_dau", label_vi="Xào / trộn thêm dầu", kcal_delta=45.0, fat_delta_g=5.0),
            ModifierSuggestionOut(id="giam_dau", label_vi="Luộc / ít dầu mỡ", kcal_delta=-40.0, fat_delta_g=-4.5),
            ModifierSuggestionOut(
                id="them_nuoc_cham",
                label_vi="Thêm nước mắm pha / sốt mè",
                kcal_delta=25.0,
                carbs_delta_g=4.5,
                fat_delta_g=0.8,
            ),
        ]
    if any(k in did for k in ("com_", "pho", "bun_", "mi_", "xoi_", "banh_mi", "chao_")) or any(
        k in nm for k in ("cơm", "phở", "bún", "mì", "xôi", "bánh mì", "cháo")
    ):
        return [
            ModifierSuggestionOut(
                id="it_com", label_vi="Bớt 1/3 cơm / bún / phở", kcal_delta=-110.0, carbs_delta_g=-24.0, protein_delta_g=-2.2
            ),
            ModifierSuggestionOut(
                id="mo_hanh", label_vi="Thêm mỡ hành / tóp mỡ", kcal_delta=65.0, fat_delta_g=7.0, carbs_delta_g=0.5
            ),
            ModifierSuggestionOut(
                id="nuoc_mam_pha",
                label_vi="Thêm nước mắm pha / tương ớt",
                kcal_delta=25.0,
                carbs_delta_g=5.5,
                protein_delta_g=0.5,
            ),
            ModifierSuggestionOut(
                id="them_trung_op",
                label_vi="Thêm 1 trứng ốp la",
                kcal_delta=90.0,
                protein_delta_g=6.5,
                fat_delta_g=7.0,
            ),
        ]
    return [
        ModifierSuggestionOut(id="them_dau", label_vi="Chế biến nhiều dầu / sốt", kcal_delta=45.0, fat_delta_g=5.0),
        ModifierSuggestionOut(id="giam_dau", label_vi="Ít dầu / gạt phần mỡ", kcal_delta=-40.0, fat_delta_g=-4.5),
        ModifierSuggestionOut(
            id="nuoc_mam_pha", label_vi="Thêm nước chấm pha", kcal_delta=22.0, carbs_delta_g=4.8, protein_delta_g=0.5
        ),
        ModifierSuggestionOut(
            id="them_com_nho", label_vi="Kèm 1 chén cơm nhỏ", kcal_delta=130.0, carbs_delta_g=28.5, protein_delta_g=2.6
        ),
    ]


def _compute_top_margin(cls_res: DishClassification | None) -> float | None:
    if cls_res is None or not cls_res.top_k:
        return None
    if len(cls_res.top_k) >= 2:
        return round(max(0.0, float(cls_res.top_k[0].confidence) - float(cls_res.top_k[1].confidence)), 4)
    return round(float(cls_res.top_k[0].confidence), 4)


def _needs_disambiguation(cls_res: DishClassification | None, top_margin: float | None, *, explicit_query: bool) -> bool:
    if explicit_query or cls_res is None:
        return False
    return bool(
        cls_res.from_open_vocab
        or cls_res.is_ood
        or (not cls_res.confident)
        or (top_margin is not None and top_margin < 0.15)
        or cls_res.top1_confidence < 0.55
        or cls_res.raps_set_size > 3
    )


def _smoothstep(lo: float, hi: float, x: float) -> float:
    if hi <= lo:
        return 1.0 if x >= hi else 0.0
    t = max(0.0, min(1.0, (x - lo) / (hi - lo)))
    return t * t * (3.0 - 2.0 * t)


def _platter_signal(*, kcal_kb: float, vis_kcal: float, vis_mass_g: float) -> float:
    if vis_kcal <= 0.0 or vis_mass_g <= 0.0:
        return 0.0
    kcal_ratio = float(vis_kcal) / max(50.0, float(kcal_kb))
    return (
        _smoothstep(420.0, 560.0, float(vis_mass_g))
        * _smoothstep(575.0, 740.0, float(vis_kcal))
        * _smoothstep(1.6, 2.5, kcal_ratio)
    )


def _estimate_mass_from_macros(prot: float, carb: float, fat: float) -> float:
    return max(120.0, round((max(0.0, prot) + max(0.0, carb) + max(0.0, fat)) * 3.8, 1))


def inverse_variance_fuse(
    *,
    kcal_kb: float,
    prot_kb: float,
    carb_kb: float,
    fat_kb: float,
    fib_kb: float | None,
    kb_mass_g: float,
    hw_kb: float,
    vis_kcal: float,
    vis_mass_g: float,
    vis_prot_g: float,
    vis_carb_g: float,
    vis_fat_g: float,
    food_area_ratio: float | None,
    multi_dish_score: float | None,
    ood_clamped: bool,
    top1_conf: float,
    top_margin: float | None,
    portion: str,
    focal_length_35mm: float | None = None,
    raps_set_size: int = 1,
    is_vn: bool = True,
) -> tuple[float, float, float, float, float, float, float, float | None, float, float, float]:
    """Log-space precision-weighted Bayesian fusion (``log K = log D + log M``) with mixture disagreement variance.

    Returns ``(est_kcal, kcal_low, kcal_high, hw, est_prot, est_carb, est_fat, est_fib, est_mass_g, w_kb, w_vis)``.
    """
    if ood_clamped or not math.isfinite(vis_kcal) or not math.isfinite(vis_mass_g) or vis_kcal <= 0.0 or vis_mass_g <= 0.0:
        hw = round(max(0.12, min(0.45, hw_kb)), 4)
        k_hat = round(min(MAX_KCAL, max(0.0, kcal_kb)), 1)
        k_lo = round(max(0.0, k_hat * (1.0 - hw)), 1)
        k_hi = round(min(MAX_KCAL, k_hat * (1.0 + hw)), 1)
        kb_mass_safe = float(kb_mass_g) if math.isfinite(float(kb_mass_g)) else 0.0
        return (
            k_hat,
            k_lo,
            k_hi,
            hw,
            round(min(MAX_PROTEIN_G, prot_kb), 1),
            round(min(MAX_CARB_G, carb_kb), 1),
            round(min(MAX_FAT_G, fat_kb), 1),
            round(fib_kb, 1) if fib_kb is not None else None,
            round(min(MAX_MASS_G, max(0.0, kb_mass_safe)), 1),
            1.0,
            0.0,
        )

    m_kb = max(30.0, float(kb_mass_g))
    m_vis = max(30.0, float(vis_mass_g))
    d_kb = max(0.15, float(kcal_kb) / m_kb)
    d_vis = max(0.15, float(vis_kcal) / m_vis)
    log_d_kb, log_d_vis = math.log(d_kb), math.log(d_vis)
    log_m_kb, log_m_vis = math.log(m_kb), math.log(m_vis)

    area = 0.50 if food_area_ratio is None else float(food_area_ratio)
    multi = 0.20 if multi_dish_score is None else float(multi_dish_score)
    f_area = 1.0 + 0.5 * max(0.0, 0.30 - area) + 0.3 * max(0.0, area - 0.80)
    f_multi = 1.0 + 0.45 * multi
    if focal_length_35mm is None:
        f_focal = 1.08
    elif 22.0 <= focal_length_35mm <= 38.0:
        f_focal = 0.90
    elif focal_length_35mm < 18.0 or focal_length_35mm > 60.0:
        f_focal = 1.22
    else:
        f_focal = 0.98

    sigma_kb_base = max(0.08, float(hw_kb) / 1.28)
    margin = float(top_margin) if top_margin is not None else float(top1_conf)
    g_conf = 1.0 + 0.8 * max(0.0, 0.65 - float(top1_conf)) + 1.0 * max(0.0, 0.15 - margin)
    raps_excess = max(0, int(raps_set_size) - 3)
    alpha_clear = _smoothstep(0.12, 0.25, margin) * _smoothstep(0.32, 0.44, float(top1_conf))
    g_raps_d = (1.0 + 0.65 * raps_excess) * (1.0 - alpha_clear) + (1.0 + 0.05 * min(6, raps_excess)) * alpha_clear
    g_raps_m = (1.0 + 0.65 * raps_excess) * (1.0 - alpha_clear) + (1.0 + 0.08 * min(5, raps_excess)) * alpha_clear

    p_unc_plate = (
        _smoothstep(3.5, 6.0, float(raps_set_size))
        * _smoothstep(370.0, 480.0, m_vis)
        * _smoothstep(450.0, 560.0, float(vis_kcal))
    )
    g_raps_d = g_raps_d * (1.0 + 25.0 * p_unc_plate)
    g_raps_m = g_raps_m * (1.0 + 25.0 * p_unc_plate)

    g_mass = 1.0
    if portion == "vua":
        r = m_vis / max(50.0, m_kb)
        if r > 1.30:
            g_mass = 1.0 + 0.45 * min(1.5, r - 1.30)
        elif r < 0.75:
            g_mass = 1.0 + 0.45 * min(1.0, 0.75 - r)

    platter_s = _platter_signal(kcal_kb=kcal_kb, vis_kcal=vis_kcal, vis_mass_g=m_vis)
    if not is_vn:
        conf_nonvn = _smoothstep(0.55, 0.70, float(top1_conf)) * (1.0 - _smoothstep(3.0, 4.5, float(raps_set_size)))
        g_domain = 1.0 + 25.0 * (1.0 - conf_nonvn)
    else:
        g_domain = 1.0
    g_platter = 1.0 + 20.0 * platter_s

    # Caloric density (kcal/g) fusion: confident in-distribution KB strongly informs density;
    # uncertain low-margin / high-RAPS / platter predictions shift smoothly to visual density.
    sigma_d_kb = sigma_kb_base * g_conf * g_raps_d * g_domain * g_platter
    sigma_d_vis = 0.70 * f_area * f_multi
    prec_d_kb = 1.0 / (sigma_d_kb * sigma_d_kb)
    prec_d_vis = 1.0 / (sigma_d_vis * sigma_d_vis)
    w_d_kb = prec_d_kb / (prec_d_kb + prec_d_vis)
    w_d_vis = 1.0 - w_d_kb
    mu_log_d = w_d_kb * log_d_kb + w_d_vis * log_d_vis
    var_d_mix = (1.0 / (prec_d_kb + prec_d_vis)) + w_d_kb * w_d_vis * ((log_d_kb - log_d_vis) ** 2)

    # Mass (g) fusion: visual + EXIF focal-length cue informs portion mass,
    # while high-confidence KB retains strong mass prior unless RAPS/margin/platter signals shift.
    sigma_m_kb = max(0.14, sigma_kb_base) * g_conf * g_raps_m * g_mass * g_domain * g_platter
    sigma_m_vis = 0.45 * f_area * f_multi * f_focal
    prec_m_kb = 1.0 / (sigma_m_kb * sigma_m_kb)
    prec_m_vis = 1.0 / (sigma_m_vis * sigma_m_vis)
    w_m_kb = prec_m_kb / (prec_m_kb + prec_m_vis)
    w_m_vis = 1.0 - w_m_kb
    mu_log_m = w_m_kb * log_m_kb + w_m_vis * log_m_vis
    var_m_mix = (1.0 / (prec_m_kb + prec_m_vis)) + w_m_kb * w_m_vis * ((log_m_kb - log_m_vis) ** 2)

    raw_fused_kcal = math.exp(mu_log_d + mu_log_m)
    k_lo_bound = min(float(kcal_kb), float(vis_kcal))
    k_hi_bound = max(float(kcal_kb), float(vis_kcal))
    raw_fused_kcal = max(k_lo_bound, min(k_hi_bound, raw_fused_kcal))
    blended_kcal = raw_fused_kcal * (1.0 - platter_s) + float(vis_kcal) * platter_s
    est_kcal = round(min(MAX_KCAL, max(0.0, blended_kcal)), 1)
    raw_fused_mass = max(min(m_kb, m_vis), min(max(m_kb, m_vis), math.exp(mu_log_m)))
    fused_mass = raw_fused_mass * (1.0 - platter_s) + float(vis_mass_g) * platter_s
    if not math.isfinite(fused_mass):
        fused_mass = float(kb_mass_g) if math.isfinite(float(kb_mass_g)) else 0.0
    est_mass_g = round(min(MAX_MASS_G, max(0.0, fused_mass)), 1)

    w_kb_raw = 0.5 * (w_d_kb + w_m_kb)
    w_kb = w_kb_raw * (1.0 - platter_s)
    w_vis = 1.0 - w_kb

    alpha_kb_macro = _smoothstep(0.35, 0.65, w_kb)
    s_macro = max(0.65, min(1.45, est_kcal / max(1.0, kcal_kb)))
    kb_p, kb_c, kb_f = prot_kb * s_macro, carb_kb * s_macro, fat_kb * s_macro
    raw_p = w_kb * prot_kb + w_vis * vis_prot_g
    raw_c = w_kb * carb_kb + w_vis * vis_carb_g
    raw_f = w_kb * fat_kb + w_vis * vis_fat_g
    atw = max(1.0, 4.0 * raw_p + 4.0 * raw_c + 9.0 * raw_f)
    norm = max(0.65, min(1.45, est_kcal / atw))
    vis_p, vis_c, vis_f = raw_p * norm, raw_c * norm, raw_f * norm
    est_prot = round(min(MAX_PROTEIN_G, max(0.0, alpha_kb_macro * kb_p + (1.0 - alpha_kb_macro) * vis_p)), 1)
    est_carb = round(min(MAX_CARB_G, max(0.0, alpha_kb_macro * kb_c + (1.0 - alpha_kb_macro) * vis_c)), 1)
    est_fat = round(min(MAX_FAT_G, max(0.0, alpha_kb_macro * kb_f + (1.0 - alpha_kb_macro) * vis_f)), 1)
    scale_fib = alpha_kb_macro * s_macro + (1.0 - alpha_kb_macro) * norm
    est_fib = round(max(0.0, fib_kb * scale_fib), 1) if fib_kb is not None else None

    sigma_log_k = math.sqrt(var_d_mix + var_m_mix)
    raw_lo = est_kcal * math.exp(-1.35 * sigma_log_k)
    raw_hi = est_kcal * math.exp(1.35 * sigma_log_k)
    hw_vis_blend = (1.0 - w_vis) * 0.12 + w_vis * 0.35
    kcal_low = round(max(0.0, min(est_kcal * (1.0 - hw_vis_blend), max(est_kcal * 0.52, raw_lo))), 1)
    kcal_high = round(min(MAX_KCAL, max(est_kcal * (1.0 + hw_vis_blend), min(est_kcal * 1.48, raw_hi))), 1)
    hw = round(max(0.12, min(0.48, max(est_kcal - kcal_low, kcal_high - est_kcal) / max(50.0, est_kcal))), 4)
    return est_kcal, kcal_low, kcal_high, hw, est_prot, est_carb, est_fat, est_fib, est_mass_g, w_kb, w_vis


def estimate_meal_calories(
    deps: MealCalorieDeps,
    *,
    image_bytes: bytes | None = None,
    dish_slug: str | None = None,
    dish_name: str | None = None,
    portion: PortionSize = "vua",
) -> MealCalorieEstimateOut:
    if portion not in PORTION_MULTIPLIERS:
        raise ApiError(422, ProblemCode.validation_error, f"Khẩu phần không hợp lệ: {portion!r}")
    has_query = bool((dish_slug and dish_slug.strip()) or (dish_name and dish_name.strip()))
    if image_bytes is None and not has_query:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            "Cần cung cấp ảnh bữa ăn hoặc tên/mã món để ước lượng calo.",
        )

    mult = PORTION_MULTIPLIERS[portion]
    kb = deps.get_kb()
    kb_est = None
    explicit_rec_matched = False
    if kb and has_query:
        kb_est, explicit_rec_matched = kb.estimate_query(
            dish_slug=dish_slug,
            dish_name=dish_name,
            portion=portion,
        )

    if has_query and kb_est is None:
        raise ApiError(404, ProblemCode.not_found, "Không tìm thấy món trong kho công thức KB.")

    if image_bytes is None:
        t0 = time.perf_counter()
        assert kb_est is not None
        rec_meta_q = kb.lookup_recognized(dish_id=kb_est.slug, dish_name=kb_est.name_vi) if kb else None
        score, grade, split = _compute_nutrition_intelligence(
            kcal=kb_est.estimated_kcal,
            protein_g=kb_est.protein_g,
            carbs_g=kb_est.carbs_g,
            fat_g=kb_est.fat_g,
            fiber_g=kb_est.fiber_g,
            slot=kb_est.slot,
            is_packaged=bool(rec_meta_q and rec_meta_q.category == "packaged"),
        )
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        src_ref = rec_meta_q.source_ref if rec_meta_q and rec_meta_q.source_ref else "Vietnam NIN / FCT 2007"
        return MealCalorieEstimateOut(
            dish_name_vi=kb_est.name_vi,
            kb_slug=None if explicit_rec_matched else kb_est.slug,
            slot=kb_est.slot,  # type: ignore[arg-type]
            portion=portion,
            portion_multiplier=kb_est.portion_multiplier,
            estimated_kcal=kb_est.estimated_kcal,
            kcal_low=kb_est.kcal_low,
            kcal_high=kb_est.kcal_high,
            estimated_mass_g=kb_est.serving_g,
            protein_g=kb_est.protein_g,
            carbs_g=kb_est.carbs_g,
            fat_g=kb_est.fat_g,
            fiber_g=kb_est.fiber_g,
            source="kb_calibrated",
            calibrated=kb_est.calibrated,
            half_width_rel=kb_est.half_width_rel,
            latency_ms=latency_ms,
            visual_kcal=None,
            domain_shift_note=None,
            ood_clamped=False,
            recognized_dish_id=kb_est.slug if explicit_rec_matched else None,
            nutrition_score=score,
            nutrition_grade=grade,
            macro_kcal_split=split,
            serving_desc_vi=rec_meta_q.serving_desc_vi if rec_meta_q and rec_meta_q.serving_desc_vi else None,
            source_ref=src_ref,
            disambiguation_required=False,
            top_margin=None,
            provenance_label_vi=_provenance_label_vi(src_ref, with_image=False),
            fusion_mode="kb_exact",
            suggested_modifiers=_suggest_modifiers(kb_est.slot, kb_est.slug, kb_est.name_vi),
        )

    # Image provided -> sanitize & run ONNX visual estimator (+ optional dish classifier)
    img = sanitize_meal_image(image_bytes)
    estimator = deps.get_estimator(required=True)
    assert estimator is not None
    vis = estimator.predict(img)

    top_candidates: list[DishCandidateOut] = []
    cls_res = None
    classifier = deps.get_dish_classifier(required=False) if kb_est is None else None
    if classifier is not None:
        cls_res = classifier.predict(img, top_k=3)
        for c in cls_res.top_k:
            rec_vua = kb.estimate_recognized(dish_id=c.dish_id, portion="vua") if kb else None
            top_candidates.append(
                DishCandidateOut(
                    dish_id=c.dish_id,
                    name_vi=c.name_vi,
                    name_en=c.name_en,
                    confidence=c.confidence,
                    kb_slug=c.kb_slug,
                    kcal_vua=rec_vua.estimated_kcal if rec_vua else None,
                )
            )

    raw_vis_kcal = round(vis.kcal * mult, 1)
    raw_vis_mass = round(vis.mass_g * mult, 1)
    raw_vis_prot = round(vis.protein_g * mult, 1)
    raw_vis_carb = round(vis.carb_g * mult, 1)
    raw_vis_fat = round(vis.fat_g * mult, 1)

    vis_kcal = min(MAX_KCAL, raw_vis_kcal)
    vis_mass = min(MAX_MASS_G, raw_vis_mass)
    vis_prot = min(MAX_PROTEIN_G, raw_vis_prot)
    vis_carb = min(MAX_CARB_G, raw_vis_carb)
    vis_fat = min(MAX_FAT_G, raw_vis_fat)

    post_mult_clamped = (
        vis_kcal < raw_vis_kcal
        or vis_mass < raw_vis_mass
        or vis_prot < raw_vis_prot
        or vis_carb < raw_vis_carb
        or vis_fat < raw_vis_fat
    )
    ood_clamped = vis.ood_clamped or post_mult_clamped
    base_note = estimator.domain_shift_note or DEFAULT_DOMAIN_SHIFT_NOTE
    detected_plates, plate_latency_ms = _detect_and_classify_plates(
        deps=deps,
        img=img,
        multi_dish_score=vis.multi_dish_score,
        classifier=classifier,
        kb=kb,
    )
    multi_dish_note = _format_multi_dish_note(detected_plates, vis.multi_dish_score)
    note = (f"{base_note} {OOD_WARNING_NOTE}" if ood_clamped else base_note) + multi_dish_note
    total_latency = round(vis.latency_ms + (cls_res.latency_ms if cls_res else 0.0) + plate_latency_ms, 3)

    top_margin = _compute_top_margin(cls_res)

    if kb_est is not None:
        rec_meta_h = kb.lookup_recognized(dish_id=kb_est.slug, dish_name=kb_est.name_vi) if kb else None
        score, grade, split = _compute_nutrition_intelligence(
            kcal=kb_est.estimated_kcal,
            protein_g=kb_est.protein_g,
            carbs_g=kb_est.carbs_g,
            fat_g=kb_est.fat_g,
            fiber_g=kb_est.fiber_g,
            slot=kb_est.slot,
            is_packaged=bool(rec_meta_h and rec_meta_h.category == "packaged"),
        )
        src_ref_h = rec_meta_h.source_ref if rec_meta_h and rec_meta_h.source_ref else "Vietnam NIN / FCT 2007"
        return MealCalorieEstimateOut(
            dish_name_vi=kb_est.name_vi,
            kb_slug=None if explicit_rec_matched else kb_est.slug,
            slot=kb_est.slot,  # type: ignore[arg-type]
            portion=portion,
            portion_multiplier=kb_est.portion_multiplier,
            estimated_kcal=kb_est.estimated_kcal,
            kcal_low=kb_est.kcal_low,
            kcal_high=kb_est.kcal_high,
            estimated_mass_g=kb_est.serving_g if kb_est.serving_g is not None else vis_mass,
            protein_g=kb_est.protein_g,
            carbs_g=kb_est.carbs_g,
            fat_g=kb_est.fat_g,
            fiber_g=kb_est.fiber_g,
            source="hybrid",
            calibrated=kb_est.calibrated,
            half_width_rel=kb_est.half_width_rel,
            latency_ms=total_latency,
            visual_kcal=vis_kcal,
            domain_shift_note=note,
            ood_clamped=ood_clamped,
            recognized_dish_id=kb_est.slug if explicit_rec_matched else (cls_res.top1_id if cls_res and cls_res.confident else None),
            recognized_confidence=cls_res.top1_confidence if cls_res and cls_res.confident else None,
            top_candidates=top_candidates,
            nutrition_score=score,
            nutrition_grade=grade,
            macro_kcal_split=split,
            serving_desc_vi=rec_meta_h.serving_desc_vi if rec_meta_h and rec_meta_h.serving_desc_vi else None,
            source_ref=src_ref_h,
            disambiguation_required=False,
            top_margin=None,
            provenance_label_vi=_provenance_label_vi(src_ref_h, with_image=True),
            fusion_mode="kb_exact",
            suggested_modifiers=_suggest_modifiers(kb_est.slot, kb_est.slug, kb_est.name_vi),
            detected_plates=detected_plates,
        )

    # Photo-only mode: run principled visual+KB fusion
    return fuse_photo_estimate(
        kb=kb,
        vis=vis,
        cls_res=cls_res,
        portion=portion,
        dish_name=dish_name,
        domain_shift_note=base_note,
        total_latency_ms=total_latency,
        top_candidates=top_candidates,
        detected_plates=detected_plates,
    )


MULTI_DISH_TRIGGER_SCORE = 0.35
MAX_PLATES_TO_CLASSIFY = 4


def _detect_and_classify_plates(
    *,
    deps: MealCalorieDeps,
    img: Any,
    multi_dish_score: float | None,
    classifier: DishClassifier | None,
    kb: KBDishCatalog | None,
) -> tuple[list[DetectedPlateOut], float]:
    """Run plate_detector on likely multi-dish images and classify up to 4 main food plates."""
    if multi_dish_score is None or multi_dish_score < MULTI_DISH_TRIGGER_SCORE:
        return [], 0.0
    pdet = deps.get_plate_detector()
    if pdet is None:
        return [], 0.0
    try:
        raw_plates, plate_latency_ms = pdet.detect(img)
    except Exception as exc:  # noqa: BLE001 — optional plate detector degrades cleanly
        log.warning("plate_detector inference failed: %s", exc)
        return [], 0.0

    plate_cls_by_idx: dict[int, tuple[str, str, float, float | None]] = {}
    if len(raw_plates) >= 2 and classifier is not None:
        w, h = img.size
        qualifying = [
            idx
            for idx, pl in enumerate(raw_plates)
            if pl.label != "drink_cup"
            and (pl.x2 - pl.x1) * (pl.y2 - pl.y1) >= 0.025
            and min(pl.x2 - pl.x1, pl.y2 - pl.y1) >= 0.08
        ]
        for idx in qualifying[:MAX_PLATES_TO_CLASSIFY]:
            pl = raw_plates[idx]
            bx1, by1 = max(0, int(round(pl.x1 * w))), max(0, int(round(pl.y1 * h)))
            bx2, by2 = min(w, int(round(pl.x2 * w))), min(h, int(round(pl.y2 * h)))
            if bx2 - bx1 < 32 or by2 - by1 < 32:
                continue
            try:
                pcls = classifier.predict(img.crop((bx1, by1, bx2, by2)), top_k=1)
                plate_latency_ms += float(pcls.latency_ms)
                if pcls.confident and (not pcls.is_ood) and pcls.top1_id and pcls.top1_name_vi:
                    rec_vua = kb.estimate_recognized(dish_id=pcls.top1_id, portion="vua") if kb else None
                    plate_cls_by_idx[idx] = (
                        pcls.top1_id,
                        pcls.top1_name_vi,
                        round(float(pcls.top1_confidence), 4),
                        rec_vua.estimated_kcal if rec_vua else None,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("plate crop classification failed: %s", exc)

    out_plates: list[DetectedPlateOut] = []
    for idx, pl in enumerate(raw_plates):
        cls_info = plate_cls_by_idx.get(idx)
        out_plates.append(
            DetectedPlateOut(
                label=pl.label,
                confidence=pl.confidence,
                x1=pl.x1,
                y1=pl.y1,
                x2=pl.x2,
                y2=pl.y2,
                dish_id=cls_info[0] if cls_info else None,
                dish_name_vi=cls_info[1] if cls_info else None,
                dish_confidence=cls_info[2] if cls_info else None,
                estimated_kcal_vua=cls_info[3] if cls_info else None,
            )
        )
    return out_plates, round(float(plate_latency_ms), 3)


def _format_multi_dish_note(plates: list[DetectedPlateOut], multi_dish_score: float | None) -> str:
    if len(plates) >= 2:
        unique_names = list(dict.fromkeys(p.dish_name_vi for p in plates if p.dish_name_vi))
        if len(unique_names) >= 2:
            joined = ", ".join(unique_names[:MAX_PLATES_TO_CLASSIFY])
            return (
                f" Phát hiện mâm nhiều món ({len(plates)} đĩa/bát: {joined}), "
                "bạn có thể chọn thêm món phụ để cộng tổng calo chính xác hơn."
            )
        return (
            f" Phát hiện mâm nhiều món ({len(plates)} đĩa/bát), "
            "bạn có thể chọn thêm món phụ để cộng tổng calo chính xác hơn."
        )
    if multi_dish_score is not None and multi_dish_score >= MULTI_DISH_TRIGGER_SCORE:
        return " Phát hiện khẩu phần nhiều món, bạn có thể chọn thêm món phụ để cộng tổng calo chính xác hơn."
    return ""


def fuse_photo_estimate(
    *,
    kb: KBDishCatalog | None,
    vis: VisualPrediction,
    cls_res: DishClassification | None,
    portion: PortionSize = "vua",
    dish_name: str | None = None,
    domain_shift_note: str = DEFAULT_DOMAIN_SHIFT_NOTE,
    total_latency_ms: float | None = None,
    top_candidates: list[DishCandidateOut] | None = None,
    detected_plates: list[DetectedPlateOut] | None = None,
) -> MealCalorieEstimateOut:
    """Fuse visual prediction + DishClassification + KB priors (shared by API service & offline eval)."""
    mult = PORTION_MULTIPLIERS[portion]
    if top_candidates is None:
        top_candidates = []
        if cls_res is not None:
            for c in cls_res.top_k:
                rec_vua = kb.estimate_recognized(dish_id=c.dish_id, portion="vua") if kb else None
                top_candidates.append(
                    DishCandidateOut(
                        dish_id=c.dish_id,
                        name_vi=c.name_vi,
                        name_en=c.name_en,
                        confidence=c.confidence,
                        kb_slug=c.kb_slug,
                        kcal_vua=rec_vua.estimated_kcal if rec_vua else None,
                    )
                )

    raw_vis_kcal = round(vis.kcal * mult, 1)
    raw_vis_mass = round(vis.mass_g * mult, 1)
    raw_vis_prot = round(vis.protein_g * mult, 1)
    raw_vis_carb = round(vis.carb_g * mult, 1)
    raw_vis_fat = round(vis.fat_g * mult, 1)

    vis_kcal = min(MAX_KCAL, raw_vis_kcal)
    vis_mass = min(MAX_MASS_G, raw_vis_mass)
    vis_prot = min(MAX_PROTEIN_G, raw_vis_prot)
    vis_carb = min(MAX_CARB_G, raw_vis_carb)
    vis_fat = min(MAX_FAT_G, raw_vis_fat)

    post_mult_clamped = (
        vis_kcal < raw_vis_kcal
        or vis_mass < raw_vis_mass
        or vis_prot < raw_vis_prot
        or vis_carb < raw_vis_carb
        or vis_fat < raw_vis_fat
    )
    ood_clamped = vis.ood_clamped or post_mult_clamped or bool(cls_res is not None and cls_res.is_ood)
    plates_out = list(detected_plates or ())
    base_note = domain_shift_note or DEFAULT_DOMAIN_SHIFT_NOTE
    multi_dish_note = _format_multi_dish_note(plates_out, vis.multi_dish_score)
    note = (f"{base_note} {OOD_WARNING_NOTE}" if ood_clamped else base_note) + multi_dish_note
    total_latency = (
        round(total_latency_ms, 3)
        if total_latency_ms is not None
        else round(vis.latency_ms + (cls_res.latency_ms if cls_res else 0.0), 3)
    )
    top_margin = _compute_top_margin(cls_res)

    # Cascade stage 1: confident in-distribution dish match (vn, asian, or global) -> variance-weighted fusion
    stage1_backed_off = False
    if cls_res is not None and cls_res.confident and cls_res.top1_id and not cls_res.is_ood and kb is not None:
        rec_est = kb.estimate_recognized(dish_id=cls_res.top1_id, portion=portion)
        if rec_est is not None:
            rec_meta = kb.lookup_recognized(dish_id=cls_res.top1_id)
            kb_slug_match = rec_meta.kb_slug if (rec_meta and rec_meta.kb_slug in kb.by_slug) else None
            is_vn = bool(rec_meta and rec_meta.category == "vn")
            kb_kcal = rec_est.estimated_kcal
            kb_prot = rec_est.protein_g
            kb_carb = rec_est.carbs_g
            kb_fat = rec_est.fat_g
            kb_fib = rec_est.fiber_g
            kb_mass = (
                rec_est.serving_g
                if rec_est.serving_g is not None
                else _estimate_mass_from_macros(kb_prot, kb_carb, kb_fat)
            )
            # Smoothly blend Top-3 KB priors across top-2 softmax margin in [0.08, 0.22]
            if top_margin is not None and len(cls_res.top_k) >= 2:
                alpha_s1_blend = 1.0 - _smoothstep(0.08, 0.22, top_margin)
                if alpha_s1_blend > 1e-4:
                    w_sum = 0.0
                    b_kcal = b_prot = b_carb = b_fat = b_fib = b_mass = 0.0
                    for cand in cls_res.top_k:
                        ce = kb.estimate_recognized(dish_id=cand.dish_id, portion=portion)
                        if ce is not None and cand.confidence >= 0.08:
                            w = float(cand.confidence)
                            w_sum += w
                            b_kcal += w * ce.estimated_kcal
                            b_prot += w * ce.protein_g
                            b_carb += w * ce.carbs_g
                            b_fat += w * ce.fat_g
                            b_fib += w * (ce.fiber_g or 0.0)
                            cmass = (
                                ce.serving_g
                                if ce.serving_g is not None
                                else _estimate_mass_from_macros(ce.protein_g, ce.carbs_g, ce.fat_g)
                            )
                            b_mass += w * cmass
                    if w_sum > 0.0:
                        kb_kcal = round((1.0 - alpha_s1_blend) * kb_kcal + alpha_s1_blend * (b_kcal / w_sum), 1)
                        kb_prot = round((1.0 - alpha_s1_blend) * kb_prot + alpha_s1_blend * (b_prot / w_sum), 1)
                        kb_carb = round((1.0 - alpha_s1_blend) * kb_carb + alpha_s1_blend * (b_carb / w_sum), 1)
                        kb_fat = round((1.0 - alpha_s1_blend) * kb_fat + alpha_s1_blend * (b_fat / w_sum), 1)
                        kb_fib = round((1.0 - alpha_s1_blend) * (kb_fib or 0.0) + alpha_s1_blend * (b_fib / w_sum), 1)
                        kb_mass = round((1.0 - alpha_s1_blend) * kb_mass + alpha_s1_blend * (b_mass / w_sum), 1)

            platter_s = _platter_signal(
                kcal_kb=float(kb_kcal) / max(0.1, mult),
                vis_kcal=float(vis.kcal),
                vis_mass_g=float(vis.mass_g),
            )
            if (not ood_clamped) and platter_s >= 0.99:
                stage1_backed_off = True
            else:
                (
                    est_kcal,
                    kcal_low,
                    kcal_high,
                    hw,
                    est_prot,
                    est_carb,
                    est_fat,
                    est_fib,
                    est_mass_g,
                    w_kb,
                    w_vis,
                ) = inverse_variance_fuse(
                    kcal_kb=kb_kcal,
                    prot_kb=kb_prot,
                    carb_kb=kb_carb,
                    fat_kb=kb_fat,
                    fib_kb=kb_fib,
                    kb_mass_g=kb_mass,
                    hw_kb=rec_est.half_width_rel,
                    vis_kcal=vis_kcal,
                    vis_mass_g=vis_mass,
                    vis_prot_g=vis_prot,
                    vis_carb_g=vis_carb,
                    vis_fat_g=vis_fat,
                    food_area_ratio=vis.food_area_ratio,
                    multi_dish_score=vis.multi_dish_score,
                    ood_clamped=ood_clamped,
                    top1_conf=cls_res.top1_confidence,
                    top_margin=top_margin,
                    portion=portion,
                    focal_length_35mm=vis.focal_length_35mm,
                    raps_set_size=cls_res.raps_set_size,
                    is_vn=is_vn,
                )
                if (not ood_clamped) and vis_kcal > 0.0 and vis_mass > 0.0:
                    k_ratio = float(vis_kcal) / max(50.0, float(kb_kcal))
                    m_ratio = float(vis_mass) / max(30.0, float(kb_mass))
                    # Calibrated VN-KB vegetable dishes (slot=="rau" with kb_slug) are systematically
                    # overestimated in watery mass/kcal by visual_v3; shield them when classifier is confident.
                    rau_kb_shield = (
                        _smoothstep(0.65, 0.85, float(cls_res.top1_confidence))
                        if (rec_meta is not None and rec_meta.slot == "rau" and kb_slug_match is not None)
                        else 0.0
                    )
                    s_nonvn = (
                        0.92
                        * (1.0 - rau_kb_shield)
                        * max(
                            _smoothstep(1.15, 1.40, k_ratio),
                            _smoothstep(1.35, 1.75, m_ratio),
                            1.0 - _smoothstep(0.55, 0.78, k_ratio),
                        )
                        if not is_vn
                        else 0.0
                    )
                    s_platter_tight = (
                        _smoothstep(395.0, 475.0, float(vis.mass_g))
                        * _smoothstep(575.0, 660.0, float(vis.kcal))
                        * _smoothstep(1.15, 1.45, k_ratio)
                    )
                    s_mass_platter = (
                        (1.0 - rau_kb_shield)
                        * _smoothstep(480.0, 560.0, float(vis.mass_g))
                        * _smoothstep(2.05, 3.0, m_ratio)
                        * _smoothstep(2.0, 3.2, k_ratio)
                    )
                    s_raps_up = (
                        _smoothstep(3.5, 6.5, float(cls_res.raps_set_size))
                        * _smoothstep(350.0, 440.0, float(vis.kcal))
                        * _smoothstep(1.25, 1.75, k_ratio)
                        if cls_res.raps_set_size >= 4
                        else 0.0
                    )
                    extra_bo = min(1.0, max(s_nonvn, s_platter_tight, s_mass_platter, s_raps_up))
                    if extra_bo > 0.0:
                        est_kcal = round(min(MAX_KCAL, max(0.0, (1.0 - extra_bo) * est_kcal + extra_bo * vis_kcal)), 1)
                        est_mass_g = round(min(MAX_MASS_G, max(0.0, (1.0 - extra_bo) * est_mass_g + extra_bo * vis_mass)), 1)
                        w_kb = w_kb * (1.0 - extra_bo)
                        w_vis = 1.0 - w_kb
                        alpha_m = _smoothstep(0.35, 0.65, w_kb)
                        s_m = max(0.65, min(1.45, est_kcal / max(1.0, kb_kcal)))
                        atw_v = max(1.0, 4.0 * vis_prot + 4.0 * vis_carb + 9.0 * vis_fat)
                        norm_v = max(0.65, min(1.45, est_kcal / atw_v))
                        est_prot = round(min(MAX_PROTEIN_G, max(0.0, alpha_m * (kb_prot * s_m) + (1.0 - alpha_m) * (vis_prot * norm_v))), 1)
                        est_carb = round(min(MAX_CARB_G, max(0.0, alpha_m * (kb_carb * s_m) + (1.0 - alpha_m) * (vis_carb * norm_v))), 1)
                        est_fat = round(min(MAX_FAT_G, max(0.0, alpha_m * (kb_fat * s_m) + (1.0 - alpha_m) * (vis_fat * norm_v))), 1)
                        if kb_fib is not None:
                            est_fib = round(max(0.0, kb_fib * (alpha_m * s_m + (1.0 - alpha_m) * norm_v)), 1)
                        kcal_low = round(min(kcal_low, est_kcal * 0.65), 1)
                        kcal_high = round(min(MAX_KCAL, max(kcal_high, est_kcal * 1.35)), 1)
                        hw = round(max(0.12, min(0.48, max(est_kcal - kcal_low, kcal_high - est_kcal) / max(50.0, est_kcal))), 4)
                zero_vis_kb_only = (not ood_clamped) and (vis_kcal <= 0.0 or vis_mass <= 0.0)
                mode: FusionMode = "kb_exact" if zero_vis_kb_only else "variance_weighted"
                log.debug(
                    "meal_calorie variance_weighted fusion",
                    extra={
                        "dish_id": cls_res.top1_id,
                        "confidence": round(cls_res.top1_confidence, 4),
                        "w_kb": round(w_kb, 4),
                        "w_vis": round(w_vis, 4),
                        "vis_kcal": vis_kcal,
                        "est_kcal": est_kcal,
                    },
                )
                ood_note_suffix = f" {OOD_WARNING_NOTE}" if ood_clamped else ""
                ov_note_suffix = (
                    " (Nhận diện mở — vui lòng xác nhận đúng món trong danh sách gợi ý.)"
                    if cls_res.from_open_vocab
                    else ""
                )
                if cls_res.from_open_vocab:
                    hw = round(max(hw, 0.25), 4)
                    kcal_low = round(min(kcal_low, max(0.0, est_kcal * (1.0 - hw))), 1)
                    kcal_high = round(min(MAX_KCAL, max(kcal_high, est_kcal * (1.0 + hw))), 1)
                cls_note = (
                    f"Gợi ý món: {rec_est.name_vi}. "
                    + (
                        f"Khẩu phần tham khảo: {rec_meta.serving_desc_vi}. "
                        if rec_meta and rec_meta.serving_desc_vi
                        else ""
                    )
                    + "Ước lượng theo ảnh chụp và bảng thành phần thực phẩm."
                    + ood_note_suffix
                    + ov_note_suffix
                    + multi_dish_note
                )
                score, grade, split = _compute_nutrition_intelligence(
                    kcal=est_kcal,
                    protein_g=est_prot,
                    carbs_g=est_carb,
                    fat_g=est_fat,
                    fiber_g=est_fib,
                    slot=rec_est.slot,
                    is_packaged=bool(rec_meta and (rec_meta.category == "packaged" or rec_meta.dish_id == "mi_tom")),
                )
                src_ref_p = rec_meta.source_ref if rec_meta and rec_meta.source_ref else "Vietnam NIN / FCT 2007"
                return MealCalorieEstimateOut(
                    dish_name_vi=rec_est.name_vi,
                    kb_slug=kb_slug_match,
                    slot=rec_est.slot,  # type: ignore[arg-type]
                    portion=portion,
                    portion_multiplier=rec_est.portion_multiplier,
                    estimated_kcal=est_kcal,
                    kcal_low=kcal_low,
                    kcal_high=kcal_high,
                    estimated_mass_g=est_mass_g,
                    protein_g=est_prot,
                    carbs_g=est_carb,
                    fat_g=est_fat,
                    fiber_g=est_fib,
                    source="hybrid",
                    calibrated=rec_est.calibrated,
                    half_width_rel=hw,
                    latency_ms=total_latency,
                    visual_kcal=vis_kcal,
                    domain_shift_note=cls_note,
                    ood_clamped=ood_clamped,
                    recognized_dish_id=cls_res.top1_id,
                    recognized_confidence=cls_res.top1_confidence,
                    top_candidates=top_candidates,
                    nutrition_score=score,
                    nutrition_grade=grade,
                    macro_kcal_split=split,
                    serving_desc_vi=rec_meta.serving_desc_vi if rec_meta and rec_meta.serving_desc_vi else None,
                    source_ref=src_ref_p,
                    disambiguation_required=_needs_disambiguation(cls_res, top_margin, explicit_query=False),
                    top_margin=top_margin,
                    provenance_label_vi=_provenance_label_vi(src_ref_p, with_image=True),
                    fusion_mode=mode,
                    suggested_modifiers=_suggest_modifiers(rec_est.slot, cls_res.top1_id, rec_est.name_vi),
                    detected_plates=plates_out,
                )

    # Cascade stage 2: classifier below threshold (non-OOD, VN candidate in top-2)
    # -> smooth blend of clear-margin small-plate VN prior & probability-weighted top-3 KB prior fused with visual.
    if (
        not stage1_backed_off
        and cls_res is not None
        and kb is not None
        and cls_res.top_k
        and not cls_res.is_ood
        and cls_res.top1_confidence >= 0.25
    ):
        has_vn_cand = any(
            (m := kb.lookup_recognized(dish_id=c.dish_id)) is not None and m.category == "vn"
            for c in cls_res.top_k[:2]
        )
        cands = []
        for cand in cls_res.top_k:
            ce = kb.estimate_recognized(dish_id=cand.dish_id, portion=portion)
            if ce is not None:
                cands.append((float(cand.confidence), ce))
        mass = sum(w for w, _ in cands)
        top1_meta = kb.lookup_recognized(dish_id=cls_res.top1_id) if cls_res.top1_id else None
        a_clear_vn = (
            (1.0 if (top1_meta is not None and top1_meta.category == "vn") else 0.0)
            * _smoothstep(0.32, 0.39, cls_res.top1_confidence)
            * _smoothstep(0.14, 0.23, top_margin or 0.0)
            * (1.0 - _smoothstep(320.0, 380.0, float(vis.mass_g)))
            * (1.0 - _smoothstep(380.0, 440.0, float(vis.kcal)))
        )
        a_low_raps = 1.0 - _smoothstep(5.5, 8.5, float(cls_res.raps_set_size))
        a_conf_entry = _smoothstep(0.25, 0.39, cls_res.top1_confidence)
        a_s2_kb = (
            1.0
            if ((not ood_clamped) and (vis_kcal <= 0.0 or vis_mass <= 0.0))
            else (a_conf_entry * max(a_clear_vn, a_low_raps))
        )
        if has_vn_cand and cands and (mass >= 0.45 or a_clear_vn > 0.25) and a_s2_kb > 0.01:
            top_ce = cands[0][1]
            top_m = (
                top_ce.serving_g
                if top_ce.serving_g is not None
                else _estimate_mass_from_macros(top_ce.protein_g, top_ce.carbs_g, top_ce.fat_g)
            )
            avg_k = sum(w * ce.estimated_kcal for w, ce in cands) / max(1e-6, mass)
            avg_p = sum(w * ce.protein_g for w, ce in cands) / max(1e-6, mass)
            avg_c = sum(w * ce.carbs_g for w, ce in cands) / max(1e-6, mass)
            avg_f = sum(w * ce.fat_g for w, ce in cands) / max(1e-6, mass)
            avg_fib = sum(w * (ce.fiber_g or 0.0) for w, ce in cands) / max(1e-6, mass)
            avg_m = sum(
                w * (ce.serving_g if ce.serving_g is not None else _estimate_mass_from_macros(ce.protein_g, ce.carbs_g, ce.fat_g))
                for w, ce in cands
            ) / max(1e-6, mass)
            b_kcal = a_clear_vn * top_ce.estimated_kcal + (1.0 - a_clear_vn) * avg_k
            b_prot = a_clear_vn * top_ce.protein_g + (1.0 - a_clear_vn) * avg_p
            b_carb = a_clear_vn * top_ce.carbs_g + (1.0 - a_clear_vn) * avg_c
            b_fat = a_clear_vn * top_ce.fat_g + (1.0 - a_clear_vn) * avg_f
            b_fib = a_clear_vn * (top_ce.fiber_g or 0.0) + (1.0 - a_clear_vn) * avg_fib
            b_mass = a_clear_vn * top_m + (1.0 - a_clear_vn) * avg_m

            s2_margin = max(0.22 * a_s2_kb, top_margin or 0.0)
            s2_raps = int(round(cls_res.raps_set_size * (1.0 - a_s2_kb) + min(3, cls_res.raps_set_size) * a_s2_kb))
            (
                est_kcal,
                kcal_low,
                kcal_high,
                hw,
                est_prot,
                est_carb,
                est_fat,
                est_fib,
                est_mass_g,
                _,
                _,
            ) = inverse_variance_fuse(
                kcal_kb=b_kcal,
                prot_kb=b_prot,
                carb_kb=b_carb,
                fat_kb=b_fat,
                fib_kb=b_fib,
                kb_mass_g=b_mass,
                hw_kb=0.22,
                vis_kcal=vis_kcal,
                vis_mass_g=vis_mass,
                vis_prot_g=vis_prot,
                vis_carb_g=vis_carb,
                vis_fat_g=vis_fat,
                food_area_ratio=vis.food_area_ratio,
                multi_dish_score=vis.multi_dish_score,
                ood_clamped=ood_clamped,
                top1_conf=cls_res.top1_confidence,
                top_margin=s2_margin,
                portion=portion,
                focal_length_35mm=vis.focal_length_35mm,
                raps_set_size=s2_raps,
                is_vn=True,
            )
            if a_s2_kb < 1.0 and vis_kcal > 0.0 and not ood_clamped:
                est_kcal = round(min(MAX_KCAL, max(0.0, a_s2_kb * est_kcal + (1.0 - a_s2_kb) * vis_kcal)), 1)
                est_mass_g = round(min(MAX_MASS_G, max(0.0, a_s2_kb * est_mass_g + (1.0 - a_s2_kb) * vis_mass)), 1)
                est_prot = round(min(MAX_PROTEIN_G, max(0.0, a_s2_kb * est_prot + (1.0 - a_s2_kb) * vis_prot)), 1)
                est_carb = round(min(MAX_CARB_G, max(0.0, a_s2_kb * est_carb + (1.0 - a_s2_kb) * vis_carb)), 1)
                est_fat = round(min(MAX_FAT_G, max(0.0, a_s2_kb * est_fat + (1.0 - a_s2_kb) * vis_fat)), 1)
                kcal_low = round(min(kcal_low, est_kcal * 0.65), 1)
                kcal_high = round(min(MAX_KCAL, max(kcal_high, est_kcal * 1.35)), 1)
                hw = round(max(0.12, min(0.48, max(est_kcal - kcal_low, kcal_high - est_kcal) / max(50.0, est_kcal))), 4)
            score, grade, split = _compute_nutrition_intelligence(
                kcal=est_kcal, protein_g=est_prot, carbs_g=est_carb, fat_g=est_fat, fiber_g=est_fib
            )
            names = ", ".join(ce.name_vi for _, ce in cands)
            log.debug(
                "meal_calorie top3_blend fusion",
                extra={
                    "candidates": [(ce.slug, round(w, 4)) for w, ce in cands],
                    "est_kcal": est_kcal,
                    "vis_kcal": vis_kcal,
                },
            )
            top_slot = cands[0][1].slot if cands else None
            top_id = cands[0][1].slug if cands else None
            top_name = cands[0][1].name_vi if cands else None
            return MealCalorieEstimateOut(
                dish_name_vi=dish_name.strip() if dish_name and dish_name.strip() else None,
                kb_slug=None,
                slot=None,
                portion=portion,
                portion_multiplier=mult,
                estimated_kcal=est_kcal,
                kcal_low=kcal_low,
                kcal_high=kcal_high,
                estimated_mass_g=est_mass_g,
                protein_g=est_prot,
                carbs_g=est_carb,
                fat_g=est_fat,
                fiber_g=est_fib,
                source="hybrid",
                calibrated=False,
                half_width_rel=hw,
                latency_ms=total_latency,
                visual_kcal=vis_kcal,
                domain_shift_note=f"Chưa rõ món cụ thể; tạm ước lượng theo các món gần nhất: {names}. Chạm vào món đúng để cập nhật số liệu.",
                ood_clamped=ood_clamped,
                recognized_dish_id=None,
                recognized_confidence=cls_res.top1_confidence,
                top_candidates=top_candidates,
                nutrition_score=score,
                nutrition_grade=grade,
                macro_kcal_split=split,
                disambiguation_required=True,
                top_margin=top_margin,
                provenance_label_vi="Bảng món ăn Mỹ Vị & Ảnh",
                fusion_mode="top3_blend",
                suggested_modifiers=_suggest_modifiers(top_slot, top_id, top_name),
                detected_plates=plates_out,
            )

    score, grade, split = _compute_nutrition_intelligence(
        kcal=vis_kcal,
        protein_g=vis_prot,
        carbs_g=vis_carb,
        fat_g=vis_fat,
        fiber_g=None,
    )
    vis_hw = 0.65 if ood_clamped else VISUAL_HALF_WIDTH_REL
    return MealCalorieEstimateOut(
        dish_name_vi=dish_name.strip() if dish_name and dish_name.strip() else None,
        kb_slug=None,
        slot=None,
        portion=portion,
        portion_multiplier=mult,
        estimated_kcal=vis_kcal,
        kcal_low=round(max(0.0, vis_kcal * (1.0 - vis_hw)), 1),
        kcal_high=round(min(MAX_KCAL, vis_kcal * (1.0 + vis_hw)), 1),
        estimated_mass_g=vis_mass,
        protein_g=vis_prot,
        carbs_g=vis_carb,
        fat_g=vis_fat,
        fiber_g=None,
        source="onnx_nutrition5k",
        calibrated=False,
        half_width_rel=vis_hw,
        latency_ms=total_latency,
        visual_kcal=vis_kcal,
        domain_shift_note=note,
        ood_clamped=ood_clamped,
        recognized_dish_id=cls_res.top1_id if cls_res else None,
        recognized_confidence=cls_res.top1_confidence if cls_res else None,
        top_candidates=top_candidates,
        nutrition_score=score,
        nutrition_grade=grade,
        macro_kcal_split=split,
        disambiguation_required=_needs_disambiguation(cls_res, top_margin, explicit_query=False),
        top_margin=top_margin,
        provenance_label_vi="Ước lượng trực quan theo khẩu phần",
        fusion_mode="visual_fallback",
        suggested_modifiers=_suggest_modifiers(None, None, dish_name),
        detected_plates=plates_out,
    )
