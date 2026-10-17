# ADR 0010 — Expo: một mã nguồn cho Android và web

- Trạng thái: Chấp nhận
- Ngày: 2026-10-17
- Phạm vi: ứng dụng khách (actor A01, A02, A03); mọi endpoint người dùng; NFR-A11Y-01, NFR-PERF-03, NFR-USE-01
- Thay cho: v1 (app Android, chưa nói web)

## Bối cảnh

Đồ án cần app Android, bản web để người thử và hội đồng dùng không cần cài, và trang khảo sát gu cho người ngoài (UC23). Nhóm nhỏ, một học kỳ. Suy luận ảnh chạy ở server (ADR 0003), nên app không cần thư viện suy luận trên máy.

Tình trạng 10/2026 (R3 §2): Expo SDK 58 ra 15/10/2026 với React Native 0.88, react-native-web 0.21.0. Expo Router mặc định xuất kiểu *server* nếu không đặt `web.output`. `expo-camera`, `expo-image-picker`, `expo-image-manipulator` chạy được trên web; `expo-keep-awake` "Web support is limited". Camera trên trình duyệt và Wake Lock cần HTTPS. Expo Go không nạp được mã native bên thứ ba; Expo khuyên dùng development build. EAS miễn phí: 15 bản Android mỗi tháng.

## Các phương án

1. **Expo (React Native) một mã nguồn, Android + web qua react-native-web.**
2. **Kotlin native + một app React web riêng.** Hai mã nguồn, gấp đôi bảo trì.
3. **Flutter (Android + web).** Một mã nguồn; nhóm không có kinh nghiệm Dart; client sinh từ OpenAPI và hệ sinh thái module Expo phải thay.
4. **Chỉ PWA.** Không có bản Android cài được như yêu cầu; camera và thông báo trên Android qua trình duyệt kém hơn.

## Quyết định

Chọn **phương án 1**.

- Expo SDK 58, TypeScript, expo-router, `web.output: "single"` đặt tường minh để nginx phục vụ tệp tĩnh.
- Ghim phiên bản SDK cho cả học kỳ. R3 khuyên chỉ lên SDK 58 nếu thư viện native cần thiết đã hỗ trợ; vì v2 không dùng VisionCamera hay TFLite trên máy, rủi ro đó không áp dụng. Nếu một module bên thứ nhất lỗi trên SDK 58 thì lùi về SDK 57.
- Development build ngay từ đầu, không dựa vào Expo Go. Gom thay đổi native để nằm trong hạn mức EAS; dùng `eas build --local` khi hết.
- Module bên thứ nhất: camera, image-picker, image-manipulator (nén 1.280 px JPEG), secure-store, sqlite, notifications, keep-awake.
- Khác biệt theo nền tảng đặt trong tệp `*.native.tsx` / `*.web.tsx`:
  - Lưu token: secure-store trên Android, cookie `HttpOnly` cho refresh trên web (ADR 0004).
  - Giữ màn hình sáng khi nấu: keep-awake trên Android; trên web dùng Wake Lock API nếu trình duyệt hỗ trợ, nếu không thì báo người dùng.
  - Lưu offline cho chế độ nấu: `expo-sqlite`. Trên web, `expo-sqlite` chạy bằng WebAssembly, cần cấu hình Metro cho tệp wasm và hai header `Cross-Origin-Embedder-Policy`, `Cross-Origin-Opener-Policy` để dùng `SharedArrayBuffer`; nginx phải đặt hai header này cho web app.
- Client API sinh từ OpenAPI (`docs/api/openapi-v1.yaml`). Outbox cho nấu xong, sự kiện, sửa chip, dùng lại đúng `Idempotency-Key`/`event_id` (ADR 0007).
- Web chạy dưới HTTPS (Cloudflare Tunnel, thiết kế v2 §10) để camera và Wake Lock hoạt động.

## Hệ quả

Tích cực:
- Một mã nguồn; luồng chụp → tải lên → long-poll → chip → mâm → nấu chạy giống nhau trên Android và web.
- Trang khảo sát (UC23) là một route của cùng app, không cần tài khoản.

Tiêu cực, cần theo dõi:
- SDK 58 mới ra hai ngày khi chọn; lỗi sớm có thể xuất hiện.
- Thông báo cục bộ trên Android 14+ chỉ đúng giờ "khoảng" nếu không có quyền exact alarm; hẹn giờ trong chế độ nấu tính theo mốc tuyệt đối, chấp nhận thông báo lệch.
- Bản web không có thông báo khi tab ở nền; người nấu trên web phải để tab mở.
- Hai nhánh lưu token và lưu offline phải được kiểm thử E2E trên cả hai nền tảng.
- Header COEP `require-corp` chặn tài nguyên khác origin không gửi CORP/CORS (ví dụ phông hay ảnh từ CDN); web app tự host mọi tài nguyên.

## Căn cứ

- R3 §2 (phiên bản, hỗ trợ web của module, EAS, khuyến nghị một mã nguồn): [03-cong-nghe-vpp-phan-tich-thiet-ke.md §2](../research/raw/03-cong-nghe-vpp-phan-tich-thiet-ke.md#2-expo--react-native-oct-2026).
- review:backend_ops#15 (offline, hẹn giờ, outbox, exact alarm): [05-soi-tai-lieu-v1-phat-hien-tho.md](../research/raw/05-soi-tai-lieu-v1-phat-hien-tho.md).
- Thiết kế v2 §9 "App", §10.
- Expo SDK 58: https://expo.dev/changelog/sdk-58 ; Expo web: https://docs.expo.dev/workflow/web/ ; keep-awake: https://docs.expo.dev/versions/latest/sdk/keep-awake/ ; getUserMedia cần HTTPS: https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia (R3 mở ngày 17/10/2026).
- `expo-secure-store` chỉ hỗ trợ Android, iOS, tvOS (không có web): https://docs.expo.dev/versions/latest/sdk/securestore/ ; `expo-sqlite` có web qua wasm, cần COEP/COOP: https://docs.expo.dev/versions/latest/sdk/sqlite/ (cả hai mở ngày 17/10/2026).
