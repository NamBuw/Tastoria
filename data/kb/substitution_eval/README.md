# Bộ đánh giá gợi ý thay thế nguyên liệu

Phục vụ thiết kế v2 §6.3: đo Hit@1, Hit@3, MRR và độ phủ của các nguồn ứng viên (bảng tra
`../substitution_pairs.yaml`, Word2Vec, kNN dinh dưỡng) và các baseline (ngẫu nhiên cùng nhóm, PMI kiểu Teng).

## Tệp

| Tệp | Nội dung | Ai viết |
|---|---|---|
| `queries.yaml` | 90 truy vấn `(id, slug món, nguyên liệu thiếu, split)`, **không có đáp án** | đã sinh (seed ghi trong tệp) |
| `answers_<mã người gán>.yaml` | đáp án của từng người gán, viết độc lập | người gán A, người gán B |
| `answers_adjudicated.yaml` | đáp án chốt sau phân xử | người phân xử (người thứ ba) |

Kiểm tệp truy vấn: `uv run --package tastoria-ml python -m tastoria_ml.kb.substitutes data/kb`.

## Vì sao truy vấn không kèm đáp án

Bảng tra do nhóm soạn là một trong các hệ được đánh giá. Nếu người soạn bảng cũng viết đáp án, bảng tra sẽ được
chấm bằng chính ý của mình và Hit@k của nó bị thổi phồng. Vì vậy đáp án phải do hai người **không** tham gia soạn
`substitution_pairs.yaml` viết, mỗi người tự làm, không xem bảng tra, không xem gợi ý của mô hình và không trao đổi
với nhau cho tới khi cả hai nộp.

## Quy trình gán

1. **Chuẩn bị.** Mỗi người gán nhận `queries.yaml`, các tệp `data/kb/recipes/<slot>/<slug>.yaml` (để biết món, cách
   nấu, vai trò của nguyên liệu) và `data/kb/ingredients.yaml` (danh sách tên chuẩn). Không nhận
   `substitution_pairs.yaml`.
2. **Gán.** Với mỗi truy vấn, hình dung mình đang nấu đúng món đó ở nhà và thiếu đúng nguyên liệu đó. Ghi:
   - `acceptable`: các nguyên liệu (tên chuẩn trong `ingredients.yaml`) mà mình **thật sự sẽ dùng thay** và món vẫn
     ra món đó hoặc biến thể quen thuộc của nó; xếp theo thứ tự ưu tiên, tối đa 5;
   - `none: true` nếu không có đồ thay hợp lý (bỏ hẳn nguyên liệu hoặc đổi món khác) — truy vấn này vẫn tính vào
     độ phủ;
   - `note` (tuỳ chọn): lý do ngắn, nhất là khi đồ thay đổi tỷ lệ (khô ↔ tươi) hoặc chỉ hợp một vùng miền.
   Không xét dị ứng hay chế độ ăn: bộ lọc BR-ALG-01/BR-DIET-01 chạy riêng lúc phục vụ.
   Không giới hạn trong cùng nhóm thực phẩm: nếu người nấu thật sự dùng đồ khác nhóm, cứ ghi; con số này cho thấy
   bộ lọc cùng nhóm làm mất bao nhiêu.
3. **Định dạng.** Mỗi người một tệp:

   ```yaml
   annotator: A            # mã, không ghi tên thật
   finished_on: 2026-11-01
   answers:
     - {id: q001, acceptable: ["bắp bò"], note: "..."}
     - {id: q002, none: true}
   ```

4. **Đo thống nhất trước phân xử.** Trên từng truy vấn: Jaccard giữa hai tập `acceptable` (trung bình trên các truy
   vấn), tỷ lệ cùng chọn `none`, và tỷ lệ trùng lựa chọn số 1. Ghi các số này vào báo cáo; nếu Jaccard trung bình
   < 0,5 thì sửa hướng dẫn (ghi phiên bản), gán lại một mẫu 20 truy vấn dev trước khi làm tiếp.
5. **Phân xử.** Người thứ ba xem các truy vấn hai người khác nhau. Đáp án chốt: tập `acceptable` = hợp của hai tập,
   trừ những đồ người phân xử thấy không hợp kèm lý do; thứ tự = thứ tự người phân xử chốt. Giữ nguyên hai tệp gốc.
6. **Khoá.** Sau khi chốt, ghi sha256 của `queries.yaml` và `answers_adjudicated.yaml` vào run MLflow (§6.4).
   Không sửa đáp án sau khi đã chạy mô hình trên split test.

## Cách dùng split

- `dev` (~30%): chọn tham số (ngưỡng điểm, trọng số trộn nguồn, số chiều Word2Vec), xem lỗi.
- `test` (~70%): chạy một lần cho mỗi cấu hình đã khoá; so sánh cặp bằng McNemar (Hit@k) hoặc bootstrap cặp (MRR).

Một gợi ý được tính là trúng nếu nằm trong `acceptable` của đáp án chốt. Truy vấn `none: true` không có gợi ý đúng
nào; hệ trả về rỗng ở đó được ghi riêng (từ chối đúng), không cộng vào Hit@k.
