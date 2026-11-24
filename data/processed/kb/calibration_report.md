# Tastoria KB & NIN Calorie Calibration Report (F9)

- **Data Version**: `nut-r1+kb1:1d2c61cc+fct2007:6dbf6d58+usda:1c93c3cb`
- **Rice Bowl (150 g cooked)**: `173.2 kcal`

## Before vs After NIN Validation Summary

| Metric | Before (n=45, pork-shoulder bug) | After (n=69, split + expanded) |
|---|---:|---:|
| `n` | 45 | 69 |
| `p80_abs_rel_error` | 0.2135 | 0.1197 |
| `p80_bootstrap_95ci` | [0.0879, 0.3352] | [0.0654, 0.2258] |
| `median_abs_rel_error` | 0.0466 | 0.0350 |
| `mean_rel_error` | -0.0432 | -0.0131 |
| `within_10pct` | 31/45 (68.9%) | 54/69 (78.3%) |
| `within_20pct` | 34/45 (75.6%) | 59/69 (85.5%) |

## Per-Slot Recipe Nutrition Summary (180 Recipes)

| Slot | Recipes | Min kcal | Median kcal | Mean kcal | Max kcal |
|---|---:|---:|---:|---:|---:|
| `man` | 75 | 69.2 | 256.4 | 268.6 | 586.6 |
| `rau` | 55 | 24.6 | 78.3 | 104.1 | 409.5 |
| `canh` | 50 | 19.1 | 119.5 | 127.2 | 381.9 |
