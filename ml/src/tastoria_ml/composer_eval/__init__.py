"""Meal-tray composer evaluation (design v2 §6.2): synthetic fridge scenarios, weight grid, Pareto fronts,
pre-registered weight rule, paired comparison against taste-only and random feasible trays.

The composer itself is NOT reimplemented: `tastoria.modules.meal.composer.compose`, `service._option` (needs per
BR-TRAY-02), `ranker.BaselineRanker` / `ranker.percentiles` (ŝ') and `schedule.solve` (CP-SAT, BR-TRAY-05) are
imported from the live backend package of the uv workspace. Only the scenario generator and an independent
feasibility checker are written here.
"""
