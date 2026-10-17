# Tính dinh dưỡng món và kiểm định calo với Viện Dinh dưỡng

Làm ngày 17/10/2026. Áp dụng BR-NUT-05, BR-NUT-06, BR-TRAY-03 (thiết kế v2 §4).

- Mã: `ml/src/tastoria_ml/kb/nutrition.py`, test `ml/tests/kb/test_nutrition.py`.
- Kết quả: `data/processed/kb/recipe_nutrition.csv` (180 công thức), `recipe_nutrition_flags.csv`
  (món bị cờ), `rice_bowl.json` (E_bát).
- Bản chép tay 45 món của Viện: `data/kb/validation/nin_dishes.yaml`.
- Chạy lại:

  ```
  uv run --package tastoria-ml python -m tastoria_ml.kb.nutrition data/kb --nin data/kb/validation/nin_dishes.yaml
  ```

- Phiên bản dữ liệu ghi kèm mỗi dòng: `nut-r1+kb1:b591fa77+fct2007:6dbf6d58+usda:1c93c3cb` (phiên bản quy tắc
  tính + 8 ký tự sha256 của `ingredients.yaml`, bảng FCT 2007 và bảng USDA). Sửa một trong các tệp đó thì
  chuỗi đổi.

## Kết quả chính

| Chỉ số | Giá trị |
|---|---|
| Số món so với Viện Dinh dưỡng | 45 |
| **Phân vị 80 của \|sai số tương đối\|** | **21,4 %** (khoảng tin cậy bootstrap 95 %: 8,8–33,5 %) |
| Trung vị \|sai số\| | 4,7 % |
| Sai số trung bình (có dấu) | −4,3 % (mình tính thấp hơn Viện) |
| Số món lệch ≤ 10 % / ≤ 20 % | 31 / 34 trên 45 |
| E_bát (150 g cơm) | 173 kcal |

Theo BR-NUT-06, nửa độ rộng khoảng calo hiển thị là **±21 %**. Khoảng tin cậy của con số này rộng (9–34 %)
vì chỉ có 45 món, và đuôi sai số do vài nguyên nhân có thể sửa được (mục 4.3). Sửa riêng cách ghép "thịt nạc
vai" thì p80 xuống khoảng 13 %.

## 1. Cách tính dinh dưỡng một khẩu phần

Phương pháp nguyên liệu của EuroFIR:

    n_k(món) = Σ_i  w_i · EP_i / 100 · n_ik · RF_ik,   chia cho số khẩu phần servings

- **w_i**: gam lúc mua trong `data/kb/recipes/<slot>/<slug>.yaml`, cho `servings` người.
- **n_ik**: giá trị trên 100 g phần ăn được, lấy theo `comp_source` của nguyên liệu: FCT 2007
  (`data/processed/fct2007`, natri lấy từ `nutrients_long.csv`) hoặc USDA (`data/processed/usda`).
- **EP_i** (tỷ lệ ăn được):
  - nguyên liệu FCT: EP = 1 − thải_bỏ/100 theo cột `refuse_pct` của FCT;
  - nguyên liệu USDA: giá trị đã là phần ăn được, EP = 1;
  - năm nguyên liệu mua cả xương/vỏ hoặc FCT thiếu tỷ lệ thải bỏ, mượn tỷ lệ của một mục FCT
    (`REFUSE_OVERRIDES`):

    | Nguyên liệu | Nguồn thành phần | Thải bỏ dùng | Lấy từ |
    |---|---|---:|---|
    | cánh gà, đùi gà, chim cút | USDA (thịt + da) | 52 % | FCT 7013 Thịt gà ta (cả con) |
    | nghêu | USDA (phần thịt) | 80 % | FCT 8048 Sò |
    | cá nục | FCT 8020 (không ghi thải bỏ) | 35 % | FCT 8026 Cá thu |

    Với đùi gà góc tư, 52 % (cả con, gồm đầu, chân, lòng) có lẽ cao hơn thực tế; chưa có số cân riêng.
- **RF** (hệ số giữ lại) = 1 cho năng lượng, đạm, béo, bột đường, chất xơ, natri, đúng BR-NUT-05 bản v2.
- **Bột đường**: FCT `glucid` là bột đường hấp thu được (năng lượng FCT đúng bằng 4·P + 9·L + 4·G); USDA
  `carb_g` tính theo hiệu số, có lẫn chất xơ, nên lấy `carb_g − fiber_g`.
- **Mì căn**: nguồn là bột gluten khô USDA 168147 (8,2 % nước). Mì căn bán ướt, giả định 68 % nước, nên nhân
  mọi giá trị với (100 − 68)/(100 − 8,2) = 0,349. Đây là giả định, chưa có số đo.
- **Bột ngọt**: không có mục thành phần; chỉ tính natri 12,3 g/100 g (theo ghi chú trong `ingredients.yaml`),
  năng lượng 0.
- **Nguyên liệu tuỳ chọn** (`optional: true`) không tính vào tổng.
- **Nguyên liệu không có thành phần** (`comp_source: null`) bị bỏ qua; tỷ lệ gam của chúng trong công thức
  ghi ở cột `uncovered_gram_share`. 25/180 công thức có phần không phủ; 4 công thức trên 5 %; hai công thức
  bị cờ: `ngon-su-su-xao-toi` 91 % (ngọn su su), `canh-xuong-ham-cu-cai` 51 % (xương ống).
- **Natri**: FCT thiếu natri ở 277/526 mục (có muối, nước mắm, xì dầu; thiếu mắm tôm, mắm tép, tương bần
  và nhiều loại cá). Cột `sodium_mg` là tổng các nguyên liệu có số, kèm `sodium_gram_share` = tỷ lệ gam
  (trong phần đã phủ) có số natri. 135/180 công thức có tỷ lệ này ≥ 0,9; 20 công thức dưới 0,5. Natri vì vậy
  là cận dưới, chưa dùng để cảnh báo.

### 1.1 Dầu mỡ khi chiên

- **Xào, áp chảo, rán ít dầu**: tính hết dầu trong công thức.
- **Chiên ngập dầu**: chỉ tính phần dầu thấm vào món. Nhận biết món chiên ngập bằng `method: chien` và
  ghi chú công thức có chữ "BR-NUT-05" (người soạn công thức đã đánh dấu). Hiện có 5 món.
- Lượng thấm = **5 g dầu trên 100 g nguyên liệu (khác dầu) cho vào chảo**, không vượt quá lượng dầu trong
  công thức. Số 5 lấy từ Bognár (2002), *Tables on weight yield of food and retention factors of food
  constituents for the calculation of nutrient composition of cooked foods (dishes)*, BFE-R--02-03,
  Karlsruhe, phần 2, cột "deep fry" của các bảng món tẩm bột: thịt lợn (bảng 7) 5, gà (bảng 13) 4, cá ít béo
  (bảng 21) 6, rau củ (bảng 27) 5 g/100 g. Bảng này đo món kiểu Đức; chưa có số cho bánh đa nem.
- Quy ra phần trăm dầu cho vào chảo ở 5 món của kho:

  | Công thức | Dầu cho vào chảo (g) | Dầu tính vào món (g) | % |
  |---|---:|---:|---:|
  | nem-ran | 440 | 31,8 | 7 % |
  | ca-ro-phi-chien | 400 | 32,0 | 8 % |
  | cha-gio-chay | 400 | 44,2 | 11 % |
  | canh-ga-chien-nuoc-mam | 300 | 36,1 | 12 % |
  | dau-hu-chien-sa | 140 | 36,4 | 26 % |

- Đối chiếu với Viện Dinh dưỡng: món "Nem rán / Chả giò chiên" của Viện ghi 4 g dầu cho một cái nem có 56 g
  nguyên liệu khác, tức 7,1 g/100 g, cao hơn 5 g/100 g của mình khoảng 40 %. Món cá thu rán của Viện: 10 g dầu
  cho 250 g cá (4 g/100 g). Số 5 nằm giữa; nem cuốn bánh đa có thể thấm nhiều hơn món tẩm bột.

## 2. E_bát: 150 g cơm (BR-TRAY-03)

FCT 2007 không có mục "cơm". Tính từ gạo tẻ máy (FCT 1004, 344 kcal/100 g) và hệ số khối lượng chín/sống
2,98 ± 0,05 (n = 140) của gạo tẻ hạt dài xát trắng luộc, Bognár (2002) phần 1 bảng 29:

    gạo sống = 150 / 2,98 = 50,3 g  →  E_bát = 50,3 × 3,44 = 173 kcal
    (đạm 4,0 g; béo 0,5 g; bột đường 38,2 g)

Đối chiếu:
- USDA "Rice, white, long-grain, regular, cooked" (168878) 130 kcal/100 g → 150 g = 195 kcal (+13 %).
- Viện Dinh dưỡng: "Cơm tẻ lưng bát" (VPF-000001) 189 kcal, "Cơm tẻ miệng bát" (VPF-000006) 258 kcal; trang
  không ghi khối lượng nên không suy ra được kcal/100 g. Nếu bát cơm của Viện cũng 150 g thì số của mình thấp hơn
  8 %.

Cơm nồi điện ở nhà nấu cạn nước (không chắt), nước trong cơm có thể ít hơn kiểu luộc của Bognár; hệ số chín/sống
thấp hơn thì E_bát cao hơn (2,6 → 198 kcal). Cần cân một mẻ cơm thật để chốt; trước khi có số đo, dùng 173 kcal.

## 3. Kiểm tra hợp lý (sanity) trên 180 công thức

| Nhóm | Số món | kcal/khẩu phần: P10 | trung vị | P90 |
|---|---:|---:|---:|---:|
| man | 75 | 143 | 252 | 424 |
| rau | 55 | 51 | 78 | 173 |
| canh | 50 | 49 | 120 | 204 |

- **Atwater**: 4·P + 9·L + 4·G so với năng lượng lấy từ bảng; 179/180 món lệch ≤ 5 %. Món lệch \> 10 % chỉ có
  `dau-bap-luoc` (−20 %): đậu bắp lấy từ USDA, năng lượng USDA tính bằng hệ số Atwater riêng từng thực phẩm,
  không phải 4/9/4.
- **Khoảng hợp lý** (kcal/khẩu phần): man 80–650, rau 10–250, canh 10–300. Món ngoài khoảng được ghi vào
  `recipe_nutrition_flags.csv`, không làm test hỏng nếu có lý do (test giữ danh sách lý do):

  | Công thức | kcal/khẩu phần | Lý do chấp nhận |
  |---|---:|---|
  | ngheu-hap-sa, ghe-hap-gung, tom-hap-sa, muc-hap-gung | 69–79 | hải sản hấp, nạc, thải bỏ vỏ lớn |
  | canh-mang-chan-gio | 382 | chân giò nhiều mỡ |
  | ca-bung | 410 | món rau nhưng có 300 g ba chỉ và đậu phụ |
  | goi-ga-bap-cai, goi-ngo-sen-tom-thit | 252, 284 | gỏi có thịt gà / tôm thịt |
  | ngon-su-su-xao-toi, canh-xuong-ham-cu-cai | 51, 45 | thiếu thành phần (91 %, 51 % gam) |
  | dau-bap-luoc | 33 | lệch Atwater, xem trên |

  Món mới rơi ra ngoài khoảng mà chưa có lý do thì test `test_outliers_are_all_justified` hỏng.
- **Test đơn vị** trên bộ dữ liệu nhỏ tính tay: tổng có thải bỏ, phần không phủ, dầu chiên ngập (thấm 20 g trên
  400 g thịt), trần lượng thấm, mượn thải bỏ cánh gà, hệ số mì căn, natri bột ngọt, chia khẩu phần, E_bát.

## 4. Kiểm định với Viện Dinh dưỡng (BR-NUT-06)

### 4.1 Cách làm

- Nguồn: công cụ "Giá trị dinh dưỡng món ăn" của Viện Dinh dưỡng,
  https://viendinhduong.vn/vi/cong-cu-va-tien-ich/gia-tri-dinh-duong-mon-an. Trang gọi
  `/api/fe/tool/getPageFoodData?page=1&pageSize=5&name=<tên>`.
- Theo quy định của thiết kế (tra tay, không tải hàng loạt): tra **từng tên món**, mỗi lần 5 kết quả, cách
  nhau 4 giây; tổng khoảng 220 lần tra (180 tên món của kho, 37 tên ngắn như "Canh cải", "Cá kho", 2 tên cơm).
  Không tải danh sách món của Viện.
- Mỗi món của Viện có một ảnh, phần "Thành phần" ghi nguyên liệu và số gam. Chép tay từ ảnh (đã xem từng
  ảnh), ghi URL ảnh, mã món, ngày truy cập vào `nin_dishes.yaml`. kcal, đạm, béo, bột đường của Viện lấy từ
  trường dữ liệu của trang.
- Chọn món có ở cả hai bên (cùng món hoặc món rất gần, cột `kb_slug`). Bỏ 6 món tìm được nhưng ảnh không ghi
  thành phần (bò lúc lắc, bò xào hành tây cà chua, sườn xào chua ngọt, gà xào sả, rau muống xào, nộm hoa chuối
  thịt gà) và 2 món không có trong kho (bò bắp luộc, canh bí đao nấu sườn).
- Tính lại kcal của **đúng thành phần Viện ghi** bằng chính bộ tính của mình (cùng bảng ghép nguyên liệu, cùng
  nguồn FCT/USDA). Như vậy sai số đo phần "bảng thành phần + cách ghép nguyên liệu + quy ước thải bỏ", không đo
  độ khác giữa công thức của mình và của Viện.
- Gam của Viện coi là phần ăn được (sống sạch), EP = 1, trừ dòng Viện ghi rõ "cả xương", "nguyên con",
  "cả con" thì tính như gam lúc mua (trừ thải bỏ). Kiểm chứng: thịt lợn thăn 36 g → 49 kcal, rau muống 312 g →
  78 kcal, cá trắm cỏ 120 g → 110 kcal khớp số Viện khi không trừ thải bỏ; gà luộc "cả xương" 605 g → 577 kcal
  khớp khi trừ 52 %. Trứng gà ta: 40 g → 57 kcal chỉ khớp khi trừ vỏ 14 %, nên trứng gà ta tính như cả vỏ.
- Quy ước nhỏ: ml coi như g (nước mắm, rượu vang, nước dừa); "bột canh" ghép với muối; "nước hàng" ghép với
  đường; "gia vị" không ghi rõ để là không phủ.
- Sai số tương đối = kcal mình / kcal Viện − 1.

### 4.2 Kết quả

Phân bố |sai số| trên 45 món: trung vị 4,7 %; **p80 = 21,4 %**; 31 món trong 10 %, 34 món trong 20 %,
11 món lệch hơn 20 %. 13 món lệch dưới 1 %, cho thấy Viện dùng cùng bảng FCT 2007 cho phần lớn nguyên liệu và
việc chép tay khớp.

| # | Món (Viện Dinh dưỡng) | Mã | Món trong kho | kcal Viện | kcal mình | Sai số |
|---|---|---|---|---:|---:|---:|
| 1 | Canh rau cua | VPF-000035 | canh-cua-rau-day-mong-toi | 60 | 106,1 | +76,8 % |
| 2 | Thịt lợn xá xíu | VPF-000141 | thit-xa-xiu | 846 | 499,5 | -41,0 % |
| 3 | Cá chép nấu dưa | VPF-000017 | ca-chep-om-dua | 1525 | 909,4 | -40,4 % |
| 4 | Canh khổ qua (mướp đắng) nhồi thịt | VPF-000031 | canh-kho-qua-nhoi-thit | 127 | 84,1 | -33,8 % |
| 5 | Thịt vịt luộc | VPF-000098 | vit-luoc | 1500 | 997,2 | -33,5 % |
| 6 | Thịt bò kho | VPF-000053 | bo-kho | 421 | 282,3 | -33,0 % |
| 7 | Vịt om sấu | VPF-000062 | vit-om-sau | 2814 | 1916,4 | -31,9 % |
| 8 | Thịt bò sốt vang | VPF-000054 | bo-sot-vang | 905 | 695,7 | -23,1 % |
| 9 | Đậu phụ kho nấm | VPF-000048 | dau-hu-kho-nam | 194 | 150,2 | -22,6 % |
| 10 | Đậu phụ kho thịt | VPF-000049 | thit-kho-dau-phu | 452 | 356,9 | -21,0 % |
| 11 | Canh rau ngót nấu thịt | VPF-000033 | canh-rau-ngot-thit-bam | 114 | 90,2 | -20,9 % |
| 12 | Canh cải xanh thịt nạc | VPF-000025 | canh-cai-xanh-thit-bam | 48 | 55,0 | +14,6 % |
| 13 | Trứng gà ta rán | VPF-000378 | trung-op-la | 81 | 91,2 | +12,6 % |
| 14 | Đậu phụ nhồi thịt sốt cà chua | VPF-000123 | dau-phu-nhoi-thit-sot-ca-chua | 248 | 220,8 | -11,0 % |
| 15 | Bí đỏ xào | VPF-000155 | bi-do-xao-toi | 66 | 71,8 | +8,8 % |
| 16 | Bí xanh xào | VPF-000156 | bi-dao-xao-tom-kho | 55 | 59,8 | +8,7 % |
| 17 | Cá Nục kho | VPF-000043 | ca-nuc-kho-ca-chua | 565 | 517,9 | -8,3 % |
| 18 | Mướp đắng xào trứng | VPF-000169 | kho-qua-xao-trung | 140 | 151,2 | +8,0 % |
| 19 | Canh cà tím nấu bung | VPF-000024 | ca-bung | 408 | 432,1 | +5,9 % |
| 20 | Trứng đúc thịt rán | VPF-000146 | trung-duc-thit | 282 | 265,4 | -5,9 % |
| 21 | Rau cải ngọt xào | VPF-000175 | cai-ngot-xao-toi | 62 | 58,5 | -5,7 % |
| 22 | Nem rán / Chả giò chiên | VPF-000133 | nem-ran | 102 | 96,3 | -5,6 % |
| 23 | Canh bầu nấu tôm | VPF-000018 | canh-bau-nau-tom | 88 | 83,9 | -4,7 % |
| 24 | Rau khoai lang xào tỏi | VPF-000178 | rau-lang-xao-toi | 114 | 119,1 | +4,5 % |
| 25 | Thịt chân giò luộc | VPF-000093 | thit-luoc | 216 | 207,0 | -4,2 % |
| 26 | Lươn xào sả ớt | VPF-000165 | luon-xao-sa-ot | 358 | 371,2 | +3,7 % |
| 27 | Thịt lợn ba chỉ kho tàu | VPF-000056 | thit-kho-tau | 260 | 268,9 | +3,4 % |
| 28 | Canh bí đỏ thịt nạt | VPF-000020 | canh-bi-do-thit-bam | 176 | 181,8 | +3,3 % |
| 29 | Rau bí xào tỏi | VPF-000172 | rau-bi-xao-toi | 95 | 92,9 | -2,2 % |
| 30 | Canh sườn khoai tây, cà rốt | VPF-000036 | canh-suon-khoai-tay-ca-rot | 316 | 322,8 | +2,1 % |
| 31 | Thịt lợn thăn luộc | VPF-000097 | thit-luoc | 49 | 50,0 | +2,0 % |
| 32 | Canh cá lóc (Các quả) nấu chua | VPF-000021 | canh-chua-ca-loc | 294 | 298,7 | +1,6 % |
| 33 | Canh cá rô đồng nấu rau cải | VPF-000023 | canh-ca-ro-nau-cai | 117 | 116,1 | -0,8 % |
| 34 | Cá Trắm kho | VPF-000047 | ca-tram-kho-rieng | 110 | 109,2 | -0,7 % |
| 35 | Canh đậu, thịt, cà chua | VPF-000027 | canh-dau-phu-ca-chua | 228 | 226,4 | -0,7 % |
| 36 | Đậu phụ sốt cà chua | VPF-000125 | dau-phu-sot-ca-chua | 320 | 321,3 | +0,4 % |
| 37 | Cá bống kho | VPF-000039 | ca-bong-kho-tieu | 110 | 109,7 | -0,3 % |
| 38 | Thịt lợn ba chỉ rang cháy cạnh | VPF-000150 | thit-rang-chay-canh | 798 | 799,9 | +0,2 % |
| 39 | Trứng gà ta luộc | VPF-000377 | trung-ga-luoc | 57 | 57,1 | +0,2 % |
| 40 | Thịt gà luộc | VPF-000094 | ga-luoc | 577 | 577,9 | +0,2 % |
| 41 | Tôm biển rang | VPF-000151 | tom-rang-me | 247 | 246,6 | -0,2 % |
| 42 | Đậu phụ rán | VPF-000124 | dau-phu-tam-hanh | 139 | 138,8 | -0,1 % |
| 43 | Cá thu rán sốt cà chua | VPF-000117 | ca-thu-sot-ca-chua | 511 | 511,3 | +0,1 % |
| 44 | Rau bắp cải luộc | VPF-000084 | bap-cai-luoc | 58 | 58,0 | +0,0 % |
| 45 | Rau muống luộc | VPF-000086 | rau-muong-luoc | 78 | 78,0 | +0,0 % |

### 4.3 Nguyên nhân sai số chính

1. **"Thịt nạc vai" của Viện là thịt nửa nạc nửa mỡ.** Kho ghép "thịt nạc vai" với FCT 7017 Thịt lợn nạc
   (139 kcal, 7 % béo). Ở các món Viện ghi "thịt nạc vai" (canh khổ qua nhồi thịt, canh rau ngót nấu thịt, đậu
   phụ kho thịt, đậu phụ nhồi thịt, nem rán) và "thịt lợn mông" (xá xíu), số béo của Viện chỉ khớp khi dùng
   FCT 7018 Thịt lợn nửa nạc nửa mỡ (260 kcal). Còn ở món Viện ghi "thịt lợn nạc", "thịt nạc băm", "thịt lợn
   thăn" thì FCT 7017 khớp. Nếu đổi 7 dòng "nạc vai"/"mông" sang 7018, p80 còn **13,0 %** (trung vị 3,3 %).
   Đề xuất (chưa làm, `ingredients.yaml` ngoài phạm vi việc này): ghép "thịt nạc vai" với FCT 7018, hoặc
   tách hai nguyên liệu "thịt nạc" và "thịt nạc vai".
2. **Thịt bò của Viện béo hơn.** Thịt bò kho (200 g thịt bò → 421 kcal, 31 g béo) và bò sốt vang (dẻ sườn) lệch
   −33 % và −23 %. FCT 7003 Thịt bò loại I chỉ 118 kcal, 3,8 % béo; ngay cả loại II (167 kcal) cũng không đủ.
   Viện có lẽ dùng số liệu thịt bò khác (bảng mới hơn hoặc phần thịt mỡ).
3. **Tỷ lệ thải bỏ của vịt và cá chép.** Vịt luộc (830 g cả xương → 1500 kcal), vịt om sấu và cá chép nấu dưa
   lệch −32 đến −40 %. Với FCT thải bỏ 55 % (vịt) và 40 % (cá chép), số của Viện chỉ khớp nếu vịt thải bỏ khoảng
   32 %; cá chép thì kể cả không trừ thải bỏ (1.293 kcal) mình vẫn thấp hơn Viện 15 %, nên còn khác cả số
   thành phần cá. Trong khi đó gà luộc, cá lóc, sườn "cả xương" khớp với thải bỏ FCT. Chưa
   rõ Viện dùng tỷ lệ nào.
4. **Ghép nguyên liệu tạm (proxy).** Đậu phụ kho nấm (−23 %): kho ghép "đậu phụ non" với USDA tofu mềm
   (61 kcal) trong khi Viện dùng số đậu phụ thường (95 kcal).
5. **Số của Viện tự mâu thuẫn.** Canh rau cua (+77 %): Viện ghi 5 g dầu nhưng chỉ 1,6 g béo cho cả bát, nghĩa là
   không tính dầu; bỏ 5 g dầu thì hai bên gần khớp. Vài trang có số đạm sai rõ (xá xíu 503 g đạm, cá trắm kho
   110 g đạm cho 120 g cá) và nem rán ghi 83,1 g bột đường cho 102 kcal. Không sửa số của Viện; các món này vẫn
   nằm trong phép đo.

## 5. Hạn chế

- p80 = 21,4 % đo trên 45 món, khoảng tin cậy 9–34 %. Đuôi sai số do vài nguyên nhân hệ thống (mục 4.3), nên
  sửa một nguyên nhân là p80 đổi nhiều. Khi đổi `ingredients.yaml` hoặc bảng thành phần, phải chạy lại lệnh ở
  đầu tài liệu; test `test_nin_file_is_complete_and_up_to_date` hỏng nếu số trong tệp YAML cũ hơn mã/dữ liệu.
- Phép so chỉ đo sai số "cùng thành phần, khác bảng/cách ghép". Không đo sai số do gam trong công thức của kho
  (lấy từ trang nấu ăn, chưa cân), độ hút dầu khi chiên ngập, hay lượng người ăn thực tế. Khoảng ±21 % là cận
  dưới của độ không chắc thật.
- Viện Dinh dưỡng không phải số đo phòng thí nghiệm của món: số của Viện cũng là số tính từ bảng thành phần.
  Khớp với Viện nghĩa là khớp cách tính của Viện.
- Hệ số giữ lại RF = 1, không tính mất nước, mất chất béo chảy ra khi kho/nướng. Với thịt ba chỉ rang, thịt
  kho, mỡ chảy ra không ăn hết thì số của mình cao hơn thực tế.
- Hệ số thấm dầu 5 g/100 g lấy từ bảng món Đức; nem cuốn bánh đa có lẽ thấm nhiều hơn (Viện: 7,1 g/100 g).
- Natri là cận dưới vì FCT thiếu natri ở nhiều mục.
- E_bát dùng hệ số chín/sống của gạo luộc kiểu châu Âu; cần cân cơm nấu nồi điện để chốt.
