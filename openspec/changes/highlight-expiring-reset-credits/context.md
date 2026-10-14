Port the fork warning to the existing upstream account list item. Use the existing nearest-expiry summary field and one timer for the list, with cleanup on unmount. For example, two credits expiring tomorrow gain a warning; unknown expiry does not. This is display-only and does not change redemption policy or the existing Reset action countdown.

Keep this change active for upstream review; sync and archive at merge as requested by the maintainer in #2065.

Fork preparation compares explicit-offset ISO timestamps as absolute instants. The interval is 72 elapsed hours, not three local dates, so daylight-saving transitions do not change the boundary. An expiry equal to the current instant is already expired. Missing or invalid expiry never produces a warning, even when credits are positive. Exact local timestamps elsewhere remain unchanged. The list owns one clock subscription while both visibility controls are enabled, and re-enabling a control refreshes its snapshot immediately.
