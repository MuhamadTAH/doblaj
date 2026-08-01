---
name: pird-security-audit
description: Security audit, vulnerability review, and remediation skill for the Pird monorepo (Kurdish-to-Iraqi-Arabic dubbing pipeline with voice cloning, Medusa storefront, dubbing dashboard, Chatwoot clone, bot-bridge, ai-gateway). Always use this skill whenever the user mentions security, vulnerabilities, hardening, auditing, penetration testing, PIRD-0 finding IDs, secrets, exposed keys, workspace isolation, GDPR or compliance, or asks to review or fix anything security-related in this codebase - even if they never say the word "audit". Always read findings_ledger.json before doing anything else.
compatibility: Requires bash, git, grep, and python3. Also recommended though optional - gitleaks, pip-audit, yarn, pnpm - for full script coverage. The Convex function sweep assumes a convex/ directory of .ts files. Built for an agent with real filesystem and shell access (e.g. Claude Code) against the Pird monorepo.
---

# Pird Security Audit

Seven manual passes on this codebase already found the same class of bug more than once, because nothing about the process remembered what had already been checked. This skill exists to fix that: it gives the audit persistent memory (a findings ledger) and replaces "impossible to hack" with something actually achievable - a smaller attack surface, breaches that are loud and contained instead of silent and total, and an attacker's cost raised higher than whatever is inside is worth.

## Before anything else

1. Read `findings_ledger.json` at this skill's root. It's the accumulated state from prior passes - what's open, what's fixed, what's genuinely unverified. Extend it instead of re-deriving the project's risk picture from a blank slate each session.
2. Read `references/architecture.md` for the current service and data map, so re-reading the whole repo cold isn't necessary just to get oriented.
3. Work out which mode this invocation calls for before touching anything (see below). Mixing modes in a single pass is exactly how a finding gets "fixed" without anyone actually checking it stuck.

## Mode 1 - Review (default)

Use this unless the user names specific finding IDs to fix, or asks outright to apply fixes.

- Stay read-only - no application code edits in this mode.
- Re-verify every ledger entry marked `fixed` before repeating that claim. A `fixed` status with no `verification_method` attached hasn't actually been checked - report it as `needs-reverification` rather than taking the label on faith.
- Run whichever scripts in `scripts/` match the finding classes in play (see "Scripts" below).
- Before writing up anything that looks new, check it against the ledger first - a match means this is a regression on an existing entry, not a fresh discovery, and should update that entry rather than spawn a duplicate.
- Produce one ranked report, Critical down to Low, in the format under "Reporting format."
- Update the ledger: new findings go in as `open`, and any status changes get recorded. Nothing gets marked `fixed` in this mode - that restraint is what makes review useful as a second opinion on fix mode's work.

## Mode 2 - Fix

Enter this mode only when the user names specific finding IDs, or says the equivalent of "fix everything Critical/High."

- Make the real code change for each finding being fixed.
- Attach an actual `verification_method` to the ledger entry: a command, a test name, or a specific reproducible check someone else could re-run. "Read the code, looks fixed" isn't one - that was precisely the standard the prior 7 passes were held to, and it's why status couldn't be trusted afterward.
- For anything in the `access-control` or `auth-bypass` class, make the verification method an automated test (see `scripts/workspace_isolation_test_template.py`) rather than a one-off manual read. This class is exactly what regresses silently across sessions when nothing but memory is checking it.
- Set `status: fixed`, `fixed_pass` to this pass's identifier, and a one-line note on what changed.
- If it isn't possible to confirm something is still fixed, say `needs-reverification`. Silence on this reads as confidence that hasn't been earned.

## Why these rules, not just what they are

- **"Impossible to hack" isn't a real target.** It either stalls the work when it can't be reached, or produces false confidence once someone stops looking. Aim instead at shrinking exposure, assuming something eventually gets through, and making that breach loud and contained rather than silent and total.
- **A secret in git history is still live even after it's deleted from the current file.** Anyone with read access to history can recover it. A secret-exposure finding only closes on rotation at the provider - file cleanup alone doesn't touch that.
- **An access-control field that exists but is never checked is its own finding**, separate from whatever it was meant to gate. It reads as protection to the next person who touches the code, which is worse than having no field at all.
- **A fix that only works if an operator remembers to configure something correctly at deploy time is half a fix.** Where feasible, have the app refuse to start in production when required security config is missing or insecure, rather than just documenting that it's required.
- **A single static secret that can act on behalf of any tenant (like one shared INTERNAL_API_KEY) is a design smell on its own**, independent of whether today's code happens to check the right things with it. Prefer per-caller or per-purpose credentials, or at minimum make sure the secret's holder still can't choose which tenant to act as.
- **In a backend where functions are public by default (e.g. Convex), "nothing calls this yet" isn't the same as "this isn't reachable."** Anything not deliberately written as an internal function is a live endpoint from the moment it's deployed, whether or not today's frontend happens to call it - audit it as if it will be called, not as if it currently is.
- **Raw secret values never belong in a report or a ledger note** - location and context are enough to act on. `secret_scan.sh` will print real values in its own local output, which is fine for the operator's own terminal, but that output should never be pasted into a third-party chat, ticket, or shared log - that's its own exposure event, independent of anything in the repo.

## Scripts

Located in `scripts/`. The paths referenced inside them (`dubbing/`, `store/`, etc.) are a best guess based on the service names in `references/architecture.md` - this skill was built from a description of the codebase, not a live read of it, so true up the paths to the real monorepo layout on first use.

- `secret_scan.sh <repo-root>` - scans the working tree and the full git history for exposed secrets. Prefers `gitleaks` if installed, falls back to pattern grep. Scanning history, not just current files, is the only way to catch a secret that's been "removed" from source but is still recoverable.
- `dep_audit.sh <repo-root>` - runs `pip-audit`, `yarn npm audit`, and `pnpm audit` across the monorepo's four package managers.
- `env_config_lint.sh <path-to-env-file>` - checks `PIRD_ENV`, `REDIS_URL` auth, and required-secret presence without ever printing a value, so its output is safe to share anywhere.
- `workspace_isolation_test_template.py` - a pytest skeleton for an automated cross-tenant isolation test, written for the pre-migration FastAPI/Supabase request path. Currently marked PENDING - see its header - until the Convex request-path question is resolved.
- `convex_function_audit.sh <path-to-convex-dir>` - sweeps every `query`/`mutation`/`action`/`httpAction` definition in a Convex codebase and flags ones with no obvious auth check nearby. Matters even before it's confirmed the dashboard calls Convex directly, since anything not written `internal*` is reachable the moment it's deployed - see PIRD-015.

## Reporting format (Review mode)

Use this exact template per finding:

```
[SEVERITY] PIRD-0NN - <title>
Class: <class>            Status: <open|fixed|needs-reverification|accepted-risk>
Location: <file:line or area>
Why it matters: <one sentence>
Verify: <command/test, or "none exists yet">
Suggested fix: <1-3 sentences>
```

List strictly in severity order. Reserve hedge words like "might" for things that genuinely weren't checked - anything a script actually ran against either turned up a result or it didn't.

## Severity

Apply the rubric in `references/severity_rubric.md` consistently rather than judging severity by feel each pass - that consistency is what makes rankings comparable across sessions.

## Project context

`references/architecture.md` holds the service and data map. `findings_ledger.json` holds the 14 findings seeded from the prior 7-pass manual review - several are marked `needs-reverification` on purpose, because the process that found them had no persistent state and no automated tests behind it. Closing that gap is what this skill is actually for; the checklist is secondary to that.
