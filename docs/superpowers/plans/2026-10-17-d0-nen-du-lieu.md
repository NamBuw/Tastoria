# D0 — Nền dữ liệu nguồn: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tải về, kiểm chứng và chuẩn hoá các nguồn dữ liệu công khai mà mọi phần sau của Tastoria cần (bảng thành phần thực phẩm, thời hạn bảo quản, tương tác Food.com, ảnh độ tươi), mỗi nguồn có ghi giấy phép và mã băm.

**Architecture:** Một package Python `tastoria_ml` (uv workspace ở gốc repo). Mỗi nguồn có một module trong `ml/src/tastoria_ml/data/` gồm hàm tải (`download`) và hàm chuẩn hoá (`parse`/`build`), chạy được bằng `python -m`. Dữ liệu thô vào `data/raw/<nguồn>/` (không commit), bảng đã chuẩn hoá vào `data/processed/<nguồn>/`.

**Tech Stack:** Python 3.12, uv, pandas, pyarrow, requests, huggingface_hub, poppler `pdftotext` (có sẵn trên máy), pytest.

**Spec:** `Tastoria_Tai_lieu_thiet_ke.pdf` (mục 2, 4) + `docs/research/raw/01-*.md`, `02-*.md` (nguồn dữ liệu đã kiểm chứng 17/10/2026).

## Global Constraints

- Python `>=3.12,<3.13`; mọi lệnh chạy qua `uv run --package tastoria-ml ...` từ gốc repo.
- Chỉ Task 1 được sửa `pyproject.toml`/`uv.lock`. Task khác thiếu thư viện thì dừng và báo lại, không tự thêm.
- Không commit gì trong `data/raw/`. Mỗi thư mục `data/raw/<nguồn>/` phải có `SOURCE.md`: URL gốc, ngày tải, giấy phép nguyên văn, trích dẫn, sha256 từng tệp.
- Tổng dung lượng tải của D0 không quá 5 GB. Đo `df -h /` trước mỗi lần tải trên 100 MB; dừng nếu ổ còn dưới 40 GB.
- Không dùng GPU. Không tải hàng loạt API của Viện Dinh dưỡng (tài liệu thiết kế mục 4.1: chỉ tra thủ công khoảng 30 món).
- Giá trị thiếu là `NaN`, không bao giờ là `0`.
- Tên tiếng Việt lưu Unicode dựng sẵn (NFC).

## Review Focus

1. Ký tự TCVN3 của chữ hoa có dấu và chữ "ư" (0xAD, soft hyphen, dễ bị pdftotext bỏ mất) → tên phải giữ đủ chữ; test `test_tcvn3_u_horn` và test tên "Rau muống", "Đậu phụ" trong FCT.
2. Ô dinh dưỡng trống hoặc "-" trong FCT 2007 → `NaN`; test `test_fct_missing_is_nan`.
3. FoodKeeper ghi thời hạn theo khoảng và đơn vị khác nhau ("1-2 Weeks", "Months") → quy về ngày; test `test_foodkeeper_days_normalization`.
4. Food.com: rating = 0 nghĩa là đánh giá không chấm sao, không phải điểm 0 → giữ dòng nhưng đánh dấu `has_rating=False`; test `test_foodcom_zero_rating_flag`.
5. Một tệp tải dở hoặc sai (mirror khác bản gốc) → kiểm kích thước và số dòng so với số đã công bố trước khi dùng; test trong từng task.

---

### Task 1: Workspace + bộ chuyển mã TCVN3 → Unicode

**Files:**
- Create: `pyproject.toml` (virtual workspace: `[tool.uv.workspace] members = ["ml"]`)
- Create: `ml/pyproject.toml` (name `tastoria-ml`, deps: pandas, pyarrow, requests, huggingface_hub, openpyxl; dev: pytest)
- Create: `ml/src/tastoria_ml/__init__.py`, `ml/src/tastoria_ml/data/__init__.py`
- Create: `ml/src/tastoria_ml/data/tcvn3.py`
- Test: `ml/tests/data/test_tcvn3.py`

**Interfaces:**
- Produces: `tcvn3_to_unicode(s: str) -> str` — đổi từng ký tự mã TCVN3 (ABC, các mã 0xA1–0xFE đọc như Latin-1) sang Unicode NFC; ký tự ASCII giữ nguyên.

- [ ] **Step 1: Write the failing tests**

```python
from tastoria_ml.data.tcvn3 import tcvn3_to_unicode

def test_known_food_name():
    assert tcvn3_to_unicode("G¹o nÕp c¸i") == "Gạo nếp cái"

def test_tcvn3_u_horn():
    # ư = 0xAD (soft hyphen), ố = 0xE8, ộ = 0xE9, ơ = 0xAC
    assert tcvn3_to_unicode("Rau muèng") == "Rau muống"
    assert tcvn3_to_unicode("D­a chuét") == "Dưa chuột"
    assert tcvn3_to_unicode("L­¬ng") == "Lương"

def test_uppercase_letters():
    # Đ = 0xA7, ậ = 0xCB, ụ = 0xF4, á = 0xB8
    assert tcvn3_to_unicode("§Ëu phô") == "Đậu phụ"
    assert tcvn3_to_unicode("§¸") == "Đá"

def test_ascii_untouched():
    assert tcvn3_to_unicode("Code 1001 (g)") == "Code 1001 (g)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tastoria-ml pytest ml/tests/data/test_tcvn3.py -q`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `tcvn3_to_unicode`** bằng một bảng tra 134 ký tự theo TCVN 5712:1993 (VN3); trả về `unicodedata.normalize("NFC", ...)`.

- [ ] **Step 4: Run tests to verify they pass** — same command, Expected: 4 passed.

---

### Task 2: Bảng thành phần thực phẩm Việt Nam 2007 → CSV

**Files:**
- Create: `ml/src/tastoria_ml/data/fct2007.py`
- Test: `ml/tests/data/test_fct2007.py`
- Output: `data/raw/fct2007/VTN_FCT_2007.pdf` + `SOURCE.md`; `data/processed/fct2007/foods.csv`, `data/processed/fct2007/nutrients_long.csv`

**Interfaces:**
- Consumes: `tcvn3_to_unicode` (Task 1)
- Produces:
  - `download(dest_dir: Path) -> Path` — tải `https://www.fao.org/fileadmin/templates/food_composition/documents/pdf/VTN_FCT_2007.pdf`.
  - `parse(pdf: Path) -> tuple[pd.DataFrame, pd.DataFrame]` → `foods` (cột: `code:int, name_vi:str, name_en:str|None, group_code:int, refuse_pct:float, energy_kcal, water_g, protein_g, lipid_g, glucid_g, fiber_g, ash_g`) và `nutrients_long` (`code, nutrient, unit, value`).
  - CLI: `python -m tastoria_ml.data.fct2007 --raw data/raw/fct2007 --out data/processed/fct2007`.

- [ ] **Step 1: Write the failing tests** (đánh dấu `pytest.mark.skipif` khi PDF chưa tải)

```python
def test_fct_food_count(foods):
    assert len(foods) == 526 and foods["code"].is_unique

def test_fct_known_names(foods):
    names = set(foods["name_vi"])
    for must in ["Rau muống", "Cà chua", "Đậu phụ"]:
        assert any(n.startswith(must) for n in names), must

def test_fct_atwater_sanity(foods):
    f = foods.dropna(subset=["energy_kcal", "protein_g", "lipid_g", "glucid_g"])
    f = f[f["energy_kcal"] > 20]
    est = 4 * f.protein_g + 4 * f.glucid_g + 9 * f.lipid_g
    ok = ((est - f.energy_kcal).abs() / f.energy_kcal) <= 0.15
    assert ok.mean() >= 0.90

def test_fct_refuse_range(foods):
    r = foods["refuse_pct"].dropna()
    assert ((r >= 0) & (r <= 100)).all()

def test_fct_missing_is_nan(nutrients_long):
    assert not (nutrients_long["value"].astype(str).str.strip() == "-").any()
```

- [ ] **Step 2: Run to verify fail** — `uv run --package tastoria-ml pytest ml/tests/data/test_fct2007.py -q` → FAIL.
- [ ] **Step 3: Implement** — `pdftotext -layout` theo từng trang (mỗi trang một thực phẩm), chuyển tên bằng `tcvn3_to_unicode`, đọc mã, nhóm (chữ số hàng nghìn), "Thải bỏ (%)" và bảng chất. Đối chiếu tay 5 trang ngẫu nhiên bằng `pdftoppm -r 80` và ghi kết quả đối chiếu vào `SOURCE.md`.
- [ ] **Step 4: Run tests** → all pass; in ra số thực phẩm, số chất, tỷ lệ ô trống.

---

### Task 3: USDA FoodData Central (Foundation + SR Legacy)

**Files:**
- Create: `ml/src/tastoria_ml/data/usda.py`
- Test: `ml/tests/data/test_usda.py`
- Output: `data/raw/usda/*.zip` + `SOURCE.md`; `data/processed/usda/foods.csv`

**Interfaces:**
- Produces: `download(dest_dir: Path) -> list[Path]` (bản Foundation JSON và SR Legacy CSV mới nhất trên trang https://fdc.nal.usda.gov/download-datasets/), `build(raw_dir: Path) -> pd.DataFrame` với cột `fdc_id:int, data_type:str, description:str, category:str, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sugars_g, sodium_mg`.

- [ ] **Step 1: Write the failing tests**

```python
def test_usda_counts(usda):
    assert (usda.data_type == "sr_legacy_food").sum() >= 7000
    assert (usda.data_type == "foundation_food").sum() >= 200

def test_usda_energy_coverage(usda):
    assert usda["energy_kcal"].notna().mean() >= 0.95

def test_usda_spinach_raw(usda):
    row = usda[usda.description.str.fullmatch(r"Spinach, raw", case=False)]
    assert len(row) >= 1 and 15 <= row.energy_kcal.iloc[0] <= 30
```

- [ ] **Step 2–4:** fail → implement (năng lượng lấy nutrient 1008, nếu thiếu thì 2047/2048 Atwater) → pass.

---

### Task 4: FSIS FoodKeeper (thời hạn bảo quản)

**Files:**
- Create: `ml/src/tastoria_ml/data/foodkeeper.py`
- Test: `ml/tests/data/test_foodkeeper.py`
- Output: `data/raw/foodkeeper/foodkeeper.json` + `SOURCE.md`; `data/processed/foodkeeper/products.csv`

**Interfaces:**
- Produces: `to_days(value: float, metric: str) -> float` (Days=1, Weeks=7, Months=30, Years=365; metric lạ → `NaN`), `build(raw_json: Path) -> pd.DataFrame` với cột `product_id, category, name, subtitle, keywords, fridge_min_days, fridge_max_days, fridge_tips`.

- [ ] **Step 1: Write the failing tests**

```python
from tastoria_ml.data.foodkeeper import to_days

def test_foodkeeper_days_normalization():
    assert to_days(1, "Weeks") == 7
    assert to_days(2, "Months") == 60
    assert to_days(3, "Days") == 3
    assert math.isnan(to_days(1, "When ripe"))

def test_foodkeeper_products(products):
    assert len(products) >= 300
    assert (products.fridge_min_days <= products.fridge_max_days).all()
```

- [ ] **Step 2–4:** fail → implement → pass. Tải: thử lần lượt các URL tài nguyên trên https://catalog.data.gov/dataset/fsis-foodkeeper-data; nếu nhận 403 thì tải bằng trình duyệt headless (playwright của `~/miniconda3/bin/python`) như người dùng bấm tải. Ghi rõ cách tải trong `SOURCE.md`.

---

### Task 5: Food.com Recipes and Interactions

**Files:**
- Create: `ml/src/tastoria_ml/data/foodcom.py`
- Test: `ml/tests/data/test_foodcom.py`
- Output: `data/raw/foodcom/RAW_recipes.csv`, `RAW_interactions.csv` + `SOURCE.md`; `data/processed/foodcom/{recipes,interactions}.parquet`, `stats.json`

**Interfaces:**
- Produces: `download(dest_dir: Path) -> list[Path]` (bản sao trên Hugging Face của Kaggle `shuyangli94/food-com-recipes-and-user-interactions`; kích thước phải khớp ±1% với 295 MB và 349 MB), `build(raw_dir: Path, out_dir: Path) -> dict` (trả và ghi `stats.json`: `n_recipes, n_users, n_interactions, n_rated, date_min, date_max, rating_hist`). `interactions.parquet`: `user_id, recipe_id, date, rating, has_rating`. `recipes.parquet`: `recipe_id, name, minutes, tags:list[str], nutrition:list[float], n_steps, ingredients:list[str], n_ingredients`.

- [ ] **Step 1: Write the failing tests**

```python
def test_foodcom_scale(stats):
    assert stats["n_interactions"] >= 1_000_000
    assert stats["n_recipes"] >= 230_000
    assert "2000" <= stats["date_min"][:4] and stats["date_max"][:4] <= "2018"

def test_foodcom_zero_rating_flag(interactions):
    z = interactions[interactions.rating == 0]
    assert len(z) > 0 and not z.has_rating.any()
    assert interactions[interactions.rating > 0].has_rating.all()
```

- [ ] **Step 2–4:** fail → implement → pass. Không tìm được bản sao khớp kích thước → dừng, báo lại (cần token Kaggle của người dùng), không dùng bản sao lệch.

---

### Task 6: Ảnh độ tươi công khai (Mendeley, CC BY 4.0)

**Files:**
- Create: `ml/src/tastoria_ml/data/freshness_sources.py`
- Test: `ml/tests/data/test_freshness_sources.py`
- Output: `data/raw/images/freshness/{local_spinach_leaf,agrifreshnet}/` + `SOURCE.md` mỗi bộ; `data/processed/freshness/manifest.csv`

**Interfaces:**
- Produces: `download(dataset: Literal["local_spinach_leaf","agrifreshnet"], dest_dir: Path) -> Path` (Mendeley public API: `skf6w2s2h2` v3 và `42m5tb7yv9` v1; chỉ tải phần ảnh gốc/processed, bỏ phần augmented), `build_manifest(raw_root: Path) -> pd.DataFrame` với cột `path, dataset, produce, label_raw, label3` trong đó `label3 ∈ {"tuoi","dung_som","dung_ngay"}` (AgriFreshNET: Fresh→tuoi, Semi-Fresh→dung_som, Rotten→dung_ngay; Local Spinach: fresh→tuoi, non-fresh→dung_ngay) và `group_id` (lô/nguồn nếu bộ dữ liệu có, để chia tập không rò rỉ).

- [ ] **Step 1: Write the failing tests**

```python
def test_manifest_labels(manifest):
    assert set(manifest.label3) <= {"tuoi", "dung_som", "dung_ngay"}
    assert set(manifest.dataset) == {"local_spinach_leaf", "agrifreshnet"}

def test_manifest_files_exist(manifest):
    sample = manifest.sample(min(200, len(manifest)), random_state=0)
    assert all(Path(p).is_file() for p in sample.path)

def test_water_spinach_present(manifest):
    ls = manifest[manifest.dataset == "local_spinach_leaf"]
    assert ls.produce.str.contains("water", case=False).any()
```

- [ ] **Step 2–4:** fail → implement → pass. Ghi danh sách nông sản thực tế của AgriFreshNET (24 loại) vào `SOURCE.md` vì trang dữ liệu chưa công bố.

---

## Done when

`uv run --package tastoria-ml pytest ml/tests -q` xanh toàn bộ; mỗi `data/raw/<nguồn>/SOURCE.md` đủ URL, ngày tải, giấy phép, trích dẫn, sha256; `docs/research/du-lieu-nguon.md` tóm tắt từng nguồn (số dòng, giấy phép, hạn chế) để đưa vào báo cáo.
