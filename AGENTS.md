# Project policy: reproduce and evaluate existing retargeting implementations

- This project reproduces existing upstream retargeting code and evaluates it. It does not develop an improved retargeting algorithm.
- Reuse each pinned upstream algorithm without changing its objectives, gains, offsets, constraints, or update equations. Do not tune it to make this robot or dataset perform better as part of the baseline.
- Keep necessary input adapters (skeleton layout, units, coordinates, missing-input policy) separate from the algorithm. State assumptions and limitations explicitly. A Quest-to-MANUS proxy is not actual MANUS input and must be labeled as such.
- Do not silently cancel upstream calibration offsets or add project-specific gain corrections, optimizers, filters, coupling, or pinch improvements to baseline results.
- Keep raw upstream output, common joint-limit processing, controller commands, and actual simulation state separate in logs and evaluation.
- Common simulation control settings must be shared across methods. Controller rate limiting is downstream simulation behavior, not an improvement to a retargeting algorithm.
- Ask the user why a change is needed and obtain confirmation before modifying existing upstream Git code. Prefer new adapters and project-owned modules. Preserve existing recordings and source assets.
- Report poor reproduction, residual errors, failed pinch/contact, missing API fields, and unverified behavior honestly; do not repair the algorithm to obtain a better score.
