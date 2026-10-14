# Local filter capacity

This change addresses the source-only recovery finding in `.hermes/triage/browser/recovery-r1/REPORT.md`. The same desktop layout clips the baseline Most reset credits choice as well as Status (inactive first) and quota choices. It is a local container-capacity defect, not a sorting defect.

A single-column filter grid is deliberate even on wide viewports because the Accounts sidebar remains bounded independently of the window width. The mobile grid was already single-column. Adding a second full-width desktop row costs 40px vertically and leaves the existing bounded account scroll region in charge of long lists.

The structural unit regression protects the local single-column contract; only real Chromium ranges and container rectangles prove label fit. The maintained screenshot regression and the external exact-asset adapter share the same geometry helper. External artifacts stay under a new successor directory, never replacing the original blocked receipt or parent UI gate.
