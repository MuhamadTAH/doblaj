# Severity rubric

Apply this consistently across passes instead of re-deriving severity by feel each time - consistency is what makes two different audit passes comparable at all.

## Critical

Live secret exposure (an active credential reachable by anyone with repo or history access) - authentication or workspace-isolation bypass that lets one tenant read or write another tenant's data - remote code execution.

Examples in this project: the hardcoded Gemini key (Critical until rotated at the provider, regardless of source-code state), cross-tenant workspace read if it's genuinely unverified.

## High

Server-side request forgery with a real internal target (cloud metadata endpoints, internal-only services) - injection that reaches a rendered surface or crosses a trust boundary - missing encryption or missing consent for biometric-adjacent data - a compliance gap that blocks launch to a jurisdiction already being served.

Examples: prompt injection into `kurdish_raw`, unverified local-FS encryption-at-rest for voice recordings, the GDPR consent/export/delete gaps.

## Medium

Missing rate limiting - an access-control field that exists but isn't enforced - unbounded resource growth (logs, uploads) with a plausible but not-yet-triggered denial-of-service path - dependency hygiene issues with no currently-known live CVE.

Examples: the unused `role` field, unbounded `vcta.log` growth, missing dependency lock files.

## Low

Hygiene issues with no realistic near-term exploit path - version-pinning style, missing documentation, code cleanliness unrelated to security.

## Two things that don't lower severity

"It's pre-launch" changes how much time there is to fix something - it doesn't change what happens if it's exploited, so it doesn't lower severity on its own. "This was fixed in an earlier pass" isn't a reason to skip re-verification either; re-verification exists precisely because earlier passes have been wrong about that before.
