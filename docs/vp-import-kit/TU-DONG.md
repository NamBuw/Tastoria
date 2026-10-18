# Dựng tệp .vpp tự động trên máy chủ Linux

Tài liệu này ghi cách đã dựng `Tastoria-UML.vpp` và `Tastoria-ERD.vpp` trên máy chủ (không giao diện, không sudo) ngày 18/10/2026, để làm lại được khi sơ đồ đổi. Cách làm tay trên Windows/macOS vẫn ở `HUONG-DAN.md`.

Kết quả nằm ở `dist/vpp/` (đã gitignore, không commit):

| Tệp | Nội dung |
|---|---|
| `Tastoria-UML.vpp` | 47 sơ đồ UML nhập từ `docs/uml/**/*.puml` |
| `Tastoria-ERD.vpp` | 62 bảng, 393 cột, 97 khoá ngoại; 8 ERD (ERD01–ERD07 theo nhóm, ERD08 tổng quan) |
| `png/uml/`, `png/erd/` | Ảnh do chính VP xuất từ hai tệp trên |

## 1. Môi trường

- Visual Paradigm Community Edition 18.1 (build 20261011), bản Linux 64-bit không cài đặt (`Visual_Paradigm_CE_Linux64_InstallFree.tar.gz`, ~860 MB), giải nén ở `~/opt/vp/Visual_Paradigm_CE_18.1` (~1,1 GB). VP dùng JRE 11 đi kèm.
- Màn hình ảo: `Xvfb :77 -screen 0 1600x1000x24`. Mọi lệnh VP chạy với `DISPLAY=:77`.
- Không kích hoạt CE và không nhập email. Lần mở đầu, hộp thoại kích hoạt có nút "No thanks, just start Visual Paradigm"; bấm nút này, VP ghi trạng thái giấy phép `Activating` vào `~/.config/VisualParadigm`. Ở trạng thái này các script dòng lệnh trong `Application/scripts` chạy được (trước khi bấm, chúng báo `License not found`).
- Ảnh xuất từ CE có một dòng chữ mờ "Powered By Visual Paradigm Community Edition" ở góc phải dưới. Không có watermark chéo.
- Script dòng lệnh phải chép từ `Application/scripts/*.sh` sang `Application/bin/` rồi chạy trong `bin/`.

## 2. Tệp dự án rỗng

Script dòng lệnh không tạo được dự án mới, nên tạo một lần bằng giao diện (qua Xvfb, chụp màn hình bằng `import -window root`, bấm bằng XTEST qua `python-xlib`): Project > New > tên `Tastoria`, Create Blank Project, Save vào `~/opt/vp/blank/blank.vpp`. Mỗi lần dựng lại thì chép tệp rỗng này ra.

Tệp `.vpp` là cơ sở dữ liệu SQLite; không sửa trực tiếp, chỉ đi qua VP.

## 3. UML: plugin PlantUML-VP có vá

Plugin `nbourdi/PlantUML-VP-Plugin` v1.0.0 có lệnh dòng lệnh qua `Plugin.sh` của VP:

```
cd ~/opt/vp/Visual_Paradigm_CE_18.1/Application/bin
DISPLAY=:77 ./Plugin.sh -project <tệp.vpp> -pluginid plugins.plantUML -pluginargs -action import -path <tệp.puml>
```

Plugin cài bằng cách chép thư mục đã giải nén vào `~/.config/VisualParadigm/plugins/`. Bản gốc không nhập được các sơ đồ của Tastoria. Các lỗi gặp và bản vá (mã nguồn ở `~/opt/vp/tools/plantuml-vp-patch/src`, dựng và cài bằng `build.sh` trong cùng thư mục):

| Lỗi | Sơ đồ bị | Vá |
|---|---|---|
| `ActorData.stereotypes` null, actor có `<<system>>` làm NPE | UCD | khởi tạo danh sách |
| `CombinedFragment.nestedCombinedFragments` null, fragment lồng nhau làm NPE | SD | khởi tạo danh sách (fragment lồng vẫn không được vẽ, plugin bỏ qua) |
| Trùng tên actor tương tác: plugin đổi tên phần tử cũ thành `..._renamed_on_import_<giờ>` và mở hộp thoại | SD | bỏ việc đổi tên |
| VP giữ tên duy nhất trong cùng cha; actor, system, package ở gốc trùng tên với sơ đồ trước bị để tên mặc định `ActorNN`, `SystemN` | UCD, CTX | mỗi sơ đồ nhập vào một model riêng mang tên sơ đồ |
| Nhánh rẽ/fork rỗng, vòng lặp không có hành động lùi, luồng đi vào nút khởi đầu | AD01, AD03, AD04 | bỏ qua cạnh không hợp lệ thay vì dừng |
| Lớp liên kết `(A, B) .. C` thành Anchor giữa hai lớp, VP từ chối | CL01, PG01 | bỏ qua cạnh đó, ghi cảnh báo |
| Hộp thoại cảnh báo modal làm treo tiến trình dòng lệnh | nhiều | in cảnh báo ra stdout |

Lỗi không cần vá plugin: trình kiểm cú pháp của plugin báo "No @startuml/@enduml found" khi dòng đầu là `@startuml <tên>`. Script dựng chép các tệp `.puml` sang `~/opt/vp/stage-puml/` và đổi dòng đầu thành `@startuml`; tệp trong repo giữ nguyên. Tên sơ đồ trong VP lấy từ tên tệp.

Plugin để JVM sống sau khi gặp ngoại lệ, nên mỗi tệp chạy một tiến trình riêng: `~/opt/vp/tools/vp_import_one.sh` chạy plugin, chờ dòng `Saved project`, giết tiến trình khi gặp ngoại lệ hoặc quá 10 phút. `~/opt/vp/tools/import_all.sh` gọi nó lần lượt theo thứ tự lớp, thành phần, gói, triển khai, ngữ cảnh, use case, trạng thái, hoạt động, tuần tự (tuần tự sau cùng để lifeline gắn được vào lớp/thành phần cùng tên). 47 tệp mất khoảng 25 phút. Một lần CL08 lỗi NPE trong Swing khi VP mở sơ đồ (`openDiagram`), chạy lại riêng tệp đó thì qua; nếu tệp nào báo `FAIL`, chạy lại `vp_import_one.sh` cho tệp đó trên cùng dự án.

## 4. ERD: plugin riêng thay cho Reverse DDL

`ReverseDDL.sh` của CE trả `Feature not supported by current edition`. Thay vì chuyển sang bản dùng thử, ERD dựng bằng một plugin nhỏ viết trên Open API của VP (CE chạy được):

1. `python3 ~/opt/vp/tools/ddl_to_spec.py db/schema_vp.sql docs/erd/gen_erd.py ~/opt/vp/erd-spec.tsv` đọc DDL (bảng, cột, kiểu, NOT NULL, DEFAULT, PK, UNIQUE một cột, FK kể cả FK ghép và 4 FK ở `ALTER TABLE`, chú thích bảng/cột) và lấy nhóm bảng ERD01–ERD07 từ `GROUPS` trong `gen_erd.py`.
2. Plugin `tastoria.erd` (mã ở `~/opt/vp/tools/tastoria-erd-plugin`, cài bằng `build.sh`):

   ```
   DISPLAY=:77 ./Plugin.sh -project Tastoria-ERD.vpp -pluginid tastoria.erd -pluginargs -spec ~/opt/vp/erd-spec.tsv
   ```

   Plugin đặt PostgreSQL làm CSDL mặc định của dự án (để kiểu cột là `uuid`, `text`, `timestamp with time zone`...), tạo bảng, cột, khoá ngoại với ràng buộc cột tham chiếu và ON DELETE, rồi tạo 8 ERD. Mỗi ERD nhóm có thêm các bảng cha ở nhóm khác mà khoá ngoại trỏ tới. Bố cục: Orthogonal.

Khi nối khoá ngoại, VP tự sinh thêm cột FK (kiểu `usersid`); plugin xoá các cột này vì cột FK thật đã có trong DDL. Chú thích tiếng Việt của bảng và cột nằm ở Documentation của từng phần tử.

## 5. Xuất ảnh để kiểm

```
DISPLAY=:77 ./ExportDiagramImage.sh -project <tệp.vpp> -out <thư mục> -diagram "*" -type png_with_background
```

Truyền `*` không kèm ngoặc kép bên trong. Khi `-diagram` chỉ có một tên, `-out` là đường dẫn tệp ảnh chứ không phải thư mục.

## 6. Việc còn phải làm tay trong VP

- Bố cục: plugin dùng bố cục tự động của VP. Sơ đồ tuần tự bị dồn mọi lifeline về x = 0; cần kéo lifeline ra trong VP (kéo trong giao diện thì thông điệp đi theo; dời bằng API thì không). UCD00 và các sơ đồ lớn cần chỉnh để use case không nằm chồng.
- Phần bị bỏ khi nhập (xem cột Vá ở mục 3): fragment lồng trong SD, 6 lớp liên kết ở CL01, các cạnh không hợp lệ ở AD04, PG01; vài quan hệ ở CP01, DP01, CTX01 có đầu mút không nhập được. Đối chiếu với ảnh trong `docs/uml/out/`.
- Làn (swimlane) của sơ đồ hoạt động không lên được: VP 18.1 chỉ hiện một đầu làn tên mặc định `PartitionN`, các hành động nằm chung một cột. Cần dựng lại làn trong VP theo ảnh mẫu.
- Tên actor đa dòng thành `Người dùng, (A02)` (dấu phẩy thay xuống dòng).
- Hai cột `jsonb` (`idempotency_keys.response_body`, `model_versions.metrics`) hiện kiểu `int4` vì danh sách kiểu PostgreSQL của VP không có `jsonb`; kiểu gốc ghi ở Documentation của cột. `bigserial` thành `int8`, ghi chú ở Documentation.
- Các ràng buộc CHECK và UNIQUE nhiều cột không được đưa vào mô hình ERD.
