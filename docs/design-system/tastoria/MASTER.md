# Design System Master File (DEPRECATED — Superseded by `editorial-v10`)

> [!IMPORTANT]
> **Bản tài liệu này đã lỗi thời (`#FFFBEB` / Claymorphism / `Be Vietnam Pro`).**
> Nguồn sự thật hiện hành duy nhất cho cả Landing và App Tastoria (`editorial-v10`) nằm tại:
> - Tokens sáng/tối W3C DTCG: [tokens.json](../tokens.json) & [tokens.dark.json](../tokens.dark.json)
> - Mã nguồn token app: [app/src/theme/tokens.ts](../../../app/src/theme/tokens.ts) & [landing/style.css](../../../landing/style.css)
> - Đặc tả Design System & Figma hợp nhất: [04-figma-va-design-system.md](../../handover/04-figma-va-design-system.md)

---

> **LOGIC:** When building a specific page, inspect `design-system/pages/[page-name].md` first.
> If that file exists, its rules **override** this Master file. Otherwise, follow the tokens and specs below.

---

**Project:** Tastoria
**Generated:** 2026-11-21 17:04:49
**Category:** Recipe & Cooking App
**Icon Standard:** Phosphor (@phosphor-icons/react), Solar, or Iconamoon

---

## Global Rules

### Color Palette & Contrast Verification

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Primary | `#9A3412` | `--color-primary` |
| On Primary | `#FFFFFF` | `--color-on-primary` |
| Secondary | `#C2410C` | `--color-secondary` |
| Accent/CTA | `#059669` | `--color-accent` |
| Background | `#FFFBEB` | `--color-background` |
| Foreground | `#0F172A` | `--color-foreground` |
| Card | `#FFFFFF` | `--color-card` |
| Card Foreground | `#0F172A` | `--color-card-foreground` |
| Muted | `#F8F2F0` | `--color-muted` |
| Muted Foreground | `#64748B` | `--color-muted-foreground` |
| Border | `#F2E6E2` | `--color-border` |
| Destructive | `#DC2626` | `--color-destructive` |
| Ring | `#9A3412` | `--color-ring` |

- **Foreground/Background Contrast:** 17.22:1 (PASS AA, APCA Lc 102.0)
- **On-Primary/Primary Contrast:** 7.31:1 (PASS AA, APCA Lc -89.4)
- **Palette Notes:** Warm terracotta + fresh green

### Typography

- **Heading Font:** Be Vietnam Pro
- **Body Font:** Noto Sans
- **Mood:** vietnamese, international, readable, clean, multilingual, accessible
- **Google Fonts:** [Be Vietnam Pro + Noto Sans](https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@300;400;500;600;700&family=Noto+Sans:wght@300;400;500;600;700&display=swap)

```css
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@300;400;500;600;700&family=Noto+Sans:wght@300;400;500;600;700&display=swap');
```

### Spacing, Radius & Motion Tokens

```css
:root {
  --space-0: 0px;
  --space-50: 2px;
  --space-100: 4px;
  --space-200: 8px;
  --space-300: 12px;
  --space-400: 16px;
  --space-500: 24px;
  --space-600: 32px;
  --space-700: 48px;
  --space-800: 64px;
  --space-900: 96px;
  --radius-card: 12px;
  --radius-control: 8px;
  --ease-out-expo: cubic-bezier(0.22, 1, 0.36, 1);
  --z-base: 0;
  --z-sticky: 20;
  --z-modal: 40;
  --z-toast: 60;
}
```

## Component Specs (Tokenized)

```css
.btn-primary {
  background: var(--color-primary);
  color: var(--color-on-primary);
  padding: var(--space-200) var(--space-300);
  border-radius: var(--radius-control);
  font-weight: 600;
  transition: transform 200ms var(--ease-out-expo), opacity 200ms var(--ease-out-expo);
}
.card {
  background: var(--color-card);
  color: var(--color-card-foreground);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  padding: var(--space-500);
}
.input {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  padding: var(--space-200) var(--space-300);
}
@media (prefers-reduced-motion: reduce) {
  .btn-primary { transition: none; }
}
```

## Style & Page Pattern

- **Style:** Claymorphism (Mobile)
- **Pattern:** App Store Style Landing
- **Section Order:** 1. Hero with device mockup, 2. Screenshots carousel, 3. Features with icons, 4. Reviews/ratings, 5. Download CTAs
- **Key Effects:** Multi-layer shadow stacks (nested View) to simulate clay depth, LinearGradient #A78BFA→#7C3AED buttons, borderRadius 40–50 outer / 32 cards / 20 buttons, Reanimated spring squish (scale 0.92 on press), BlurView glass-clay hybrid cards, floating blobs with slow ±20px drift, Haptics Light on every press

## Anti-Patterns & Pre-Delivery Gate

- Avoid: Muted colors
- Avoid: Low energy
- Avoid generic default system sans fonts or legacy unapproved icon packs; standardize on Phosphor, Solar, or Iconamoon.
- Avoid arbitrary `z-index` spikes (`>= 999`) or full-card background gradients.
- [ ] Run `check_contrast.py` on all semantic fg/bg pairs (`>= 4.5:1` AA, APCA `|Lc| >= 60`).
- [ ] Run `validate_tokens.py` on DTCG `tokens.json`.
- [ ] Run `check_anti_slop.py` on generated UI & CSS files.
