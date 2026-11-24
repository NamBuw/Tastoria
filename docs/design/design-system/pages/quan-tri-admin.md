# Page Override: `quan-tri-admin.md` (`/quan-tri`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/quan-tri` (`app/src/app/quan-tri.tsx`, outside `(tabs)/` — Strictly role-gated: `admin` | `ml_operator` ONLY; `curator` is CLI-only with 0 HTTP `/admin/*` endpoints per `openapi-v1.yaml:2936–3184`)

## Role Access & Navigation Rules
- **Visibility:**
  - Desktop (`>= 1024px`) & Tablet (`768–1023px`): Shown in left `AppShell` sidebar rail with `shield` SVG icon ONLY when `user.role === 'admin' || user.role === 'ml_operator'`.
  - Mobile (`< 768px`): Shown as a top-level banner/card in `/cai-dat` and Home header overflow menu ONLY when `user.role === 'admin' || user.role === 'ml_operator'` (never added as a 6th bottom tab).
  - Unauthorized (`user.role === 'user' || user.role === 'curator'`): Direct URL navigation renders a clear `403` access-denied guard (`[data-testid="admin-forbidden"]`, `"Trang này chỉ dành cho quản trị viên (admin) hoặc vận hành mô hình (ml_operator)"` + `"Về Bếp nhà"` CTA) **without firing any unauthorized `/admin/*` HTTP requests** (zero leaked data, zero `403` audit-log spam).

## Strict Role-Partitioned Sub-Tabs & Data Density Overrides
- **`admin` Role ONLY (renders ONLY these 2 tabs; never mounts/prefetches `ml_operator` tabs):**
  1. **Yêu cầu dữ liệu (DSR Queue):** Filter pills (`flex-wrap: wrap`) by `status` (`received`, `in_progress`, `completed`, `rejected`) & `type` (`correct`, `restrict`, `object`, `export`, `delete`). Highlight overdue/near-due `due_at` with `warn` / `danger` badge. Manual requests (`correct|restrict|object`) expose `"Xử lý"` drawer requiring `note` (`1..2000` chars); automatic requests show read-only `"Tự động"`.
  2. **Nhật ký kiểm toán (Audit Log):** Filter bar (`actor_user_id`, `entity`, `action`, `from..to`) + keyset-paginated data table (`tabular-nums` timestamps, `monospace` `request_id` copy button with `overflow-wrap: anywhere`).
- **`ml_operator` Role ONLY (renders ONLY these 2 tabs; never mounts/prefetches `admin` tabs):**
  1. **Đăng ký mô hình (Model Registry & Deployments):** 4 active deployment summary cards (`detector`, `freshness`, `ranker`, `substitution`) + version table showing `version`, SHA-256 prefix (`monospace`, `overflow-wrap: anywhere`), `preprocess_version`, `metrics`, `status` badge, `is_active` badge, and copyable CLI commands (`tastoria mlops gate|deploy|rollback ...` styled with `overflow-wrap: anywhere; word-break: break-word;` — read-only UI per OpenAPI).
  2. **Đợt khảo sát (Surveys):** Table of `version`, `is_open` status badge, and `respondents_completed / respondents_total` horizontal progress bar (`tabular-nums`).
- **Mobile Table Adaptation (`< 768px`):** Transform wide desktop tables into stacked key-value cards (`Card` per row) with wrapped monospace boxes so `scrollWidth <= innerWidth` holds down to `320px`.
