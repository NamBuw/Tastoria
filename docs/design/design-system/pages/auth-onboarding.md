# Page Override: `auth-onboarding.md` (`AuthShell`, `dang-nhap`, `dang-ky`, `quen-mat-khau`, `dat-lai-mat-khau`, `onboarding/*`, `cai-dat`)

**Inherits:** `docs/design/design-system/MASTER.md`  
**Route(s):** `/(auth)/*`, `/dat-lai-mat-khau`, `/onboarding`, `/onboarding/ho-so`, `/cai-dat`

## Surface & Color Overrides
- **Fix `AuthShell.tsx` Hardcoded Colors:**
  - Replace hardcoded `#F3512C` with `c.editorialSurface` (`#B63922` Light / `#381B14` Dark).
  - Replace legacy `#26291E` editorial copy with `c.onEditorial` (`#FAF5EB` Light / `#F7EFDF` Dark) so contrast jumps from `4.25:1` (FAIL) to `5.37:1` (Light) / `13.76:1` (Dark).
  - Replace hardcoded `#DCEB91` `photoNote` bar with `c.limeSurface` (`#D9EE74` Light with `c.text` `#2A211B` = `12.34:1`; `#2C3318` Dark with `c.text` `#F7EFDF` = `11.52:1`).
- **Destructive Zone (`cai-dat` Delete Account):** Visually separated bottom accordion section bordered with `c.danger` (`>= 1px`), requiring re-auth password (`403 reauth_failed` handled inline).

## Layout & Form Overrides
- **Auth (`wide >= 960px`):** `maxWidth: 1600` split layout (`48%` left editorial panel + centered `400px` form column). Mobile `< 960px`: single-column focused form (`paddingHorizontal: 24`).
- **Onboarding & Settings (`cai-dat`):** Desktop `>= 1024px` caps single-column form flow at `maxWidth: 680px` (or 2-column settings card grid up to `960px` for `cai-dat` sections) inside the `1240px` shell so inputs stay comfortable (`<= 68ch`).
- **Iconography & Field A11y:** Replace `↗` (`AuthShell.tsx:27`), `←` (`AuthShell.tsx:37`), `→` (`dang-nhap.tsx:62`), and `+`/`−` (`cai-dat.tsx:56`) with SVG `<Icon>`. Password eye toggle uses `eye` / `eye-off` SVG + `accessibilityLabel` (`Hiện mật khẩu` / `Ẩn mật khẩu`). Both `AuthField` and `Field` MUST wire `nativeID` on `<T v="label">` + `aria-labelledby` on `<TextInput>` (alongside `accessibilityLabel`). Gate `Quản trị` banner in `cai-dat` strictly on `user.role === 'admin' || user.role === 'ml_operator'`.
- **Granular Consent:** 3 `PolicyCard` switches MUST initialize **unchecked** (`false`), with expandable `text_vi` and clear `409 policy_outdated` auto-refetch recovery.
