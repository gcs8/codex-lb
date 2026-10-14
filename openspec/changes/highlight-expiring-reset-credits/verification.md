# Verification

Base: upstream `f8ffbac2099a113fba54dfd8d77774f5bca80ffa` (`main`).

- Account list expiry, account list, item and page suites: **56 passed**.
- Includes exact 72-hour boundary, elapsed/missing/invalid expiry, zero credits, both visibility controls, time advancing without refetch, refreshed data, and timer cleanup.
- Frontend ESLint, TypeScript and Vite build: passed.
- Strict change validation: passed. `openspec validate --specs --strict`: **67 passed, 0 failed**.
- Simplicity budgets and `git diff --check`: passed.
- Desktop (1440px) and mobile (390px) before/after screenshots captured with Playwright using synthetic data; after screenshots checked for horizontal page overflow. Images are in `evidence/`.

## Scope and limits

Only the relevant local CI subset was run; the full repository CI matrix and cloud review remain merge gates. No deployment or migration changes. Screenshots use API fixtures. The change stays active until upstream merge, following maintainer guidance on #2065.

## Fork lane preparation

The results above and committed screenshots are the source author's evidence for upstream base `f8ffbac2099a113fba54dfd8d77774f5bca80ffa`, not execution evidence for the composed fork candidate. The fork preparation base is `bdb8a4e61db9f2bcd423cb68f04c690d75b970b5`; source head is `acd558b0e715ab34b6ad7e9f108bc2904f359a20`.

Additional product-path regressions cover explicit offsets, the 72-hour boundary to the millisecond, daylight-saving changes, and re-enabling each visibility control after expiry. The new re-enable regressions failed on the source implementation. A per-list cached clock subscription refreshes on subscription and avoids a stale warning when the timer restarts. Existing usage-panel and redemption-dialog exact timestamp tests are retained.

Gate commands, exact executed commits, raw logs, and results are recorded in the campaign's external `pr-2577` receipt. The parent-provided Bun executable is version 1.4.3, while repository CI pins 1.3.14. No global tool installation or lockfile change was made.

The composed candidate has not been exercised in an actual browser and has no fresh before/after desktop/mobile screenshots. This is an explicit screenshot/browser hold, not a pass based on the inherited PNG files. No image builds, deployment, production requests, or upstream writes are authorized.
