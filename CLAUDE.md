# Pird — Claude Code Guide

Pird is a Kurdish-rooted company ("bridge") connecting Kurdish and Arabic markets
through dubbing, an AI-powered Medusa store, omnichannel social bots, and a
shared AI gateway. Monorepo layout:

```
store/backend/      Medusa.js backend (Node 20+, port 9000)
store/storefront/   Next.js 14 storefront (yarn 4.12, port 8000)
studio/dubbing/     FastAPI video-dubbing pipeline (Python, port 8002)
studio/ai-gateway/  Express AI gateway (port 4000)
studio/bot-bridge/  Express Chatwoot webhook (port 4001)
studio/comment-bot/ Express Meta comments handler (port 4002)
chatwoot-clone/     Chatwoot source, run via docker compose (port 3000)
shared/             Docs + translation extractor (no build)
tools/SkillSpector/ NVIDIA security scanner (Python venv)
```

## Production platform (live)

**Read `studio/dubbing/PRODUCTION.md` before any change that touches the
production dubbing platform.** It documents the live stack: which services
run where (Cloudflare Pages / Azure VM / RunPod / Convex / R2 / Clerk / Suby),
how to verify each layer with curl, how to deploy (`pirdupdate` on the VM),
and the list of leaked secrets that need rotation.

Key facts as of `ab3ba7b`:
- Frontend: `https://doblaj.com` (Cloudflare Pages)
- Backend: `https://api.doblaj.com` → Azure VM `dubbing-bot-vps` (FastAPI on `127.0.0.1:8002`)
- Convex: `https://upbeat-scorpion-447.convex.cloud` (deployment hash `20260728T224050Z-a42e7a9c8375`)
- RunPod GPU: endpoint `3wz0kfi2xnbkxx`, image `muhammadtarq/pird-dubbing-worker:v6`

## Architecture & skills

Read `.claude/skills/project-architecture/SKILL.md` before touching anything
that crosses services. The agent registry at `.claude/agents/` defines who
owns what; pick the right agent before writing code in a domain you don't own.

## Run & test commands (per service)

| Service              | Run                          | Test                                | Lint     | Build         | Port |
|----------------------|------------------------------|-------------------------------------|----------|---------------|------|
| store/backend        | `yarn dev`                   | `yarn test:unit` (needs Postgres for integration) | none     | `yarn build`   | 9000 |
| store/storefront     | `yarn dev`                   | none                                | `yarn lint` | `yarn build` | 8000 |
| studio/dubbing       | `python main.py` (or `uvicorn main:app --reload --port 8002`) | `pytest` (bare `test_*.py` files; install pytest first) | none | n/a | 8002 |
| studio/ai-gateway    | `npm run dev` (package.json missing — see gotchas) | none | none | none | 4000 |
| studio/bot-bridge    | `npm run dev` (package.json missing) | none | none | none | 4001 |
| studio/comment-bot   | `npm run dev` (package.json missing) | none | none | none | 4002 |
| chatwoot-clone       | `docker compose up -d` (uses official image, not local build) | `pnpm test` (frontend vitest only) | `pnpm eslint` | n/a | 3000 |

### Known gotchas

- **`ai-gateway`, `bot-bridge`, `comment-bot`** have READMEs that document
  `npm run dev` but no `package.json` on disk. Their build agents must
  scaffold the project before these commands are real.
- **`store/backend` integration tests need Postgres** (`DATABASE_URL`); won't
  run on the default SQLite.
- **`store/storefront` has no test runner** — verification means `yarn build`.
- **`studio/dubbing` port mismatch**: README and `main.py` use 8002,
  Dockerfile uses 8000. Don't change one without the other.
- **`chatwoot-clone/docker-compose.yml` ships plaintext credentials**
  (Supabase pooler password, JWT secret). Move to env vars before any external
  commit.
- **Mismatched toolchains**: `store/backend` needs Node ≥20, `chatwoot-clone`
  needs Node 24 + pnpm 10, `store/storefront` uses yarn 4.12. No monorepo-root
  install.
- **Backup dirs** `store/backend.pird-backup/` and `store/storefront.pird-backup/`
  are abandoned copies — ignore them.
- **`tools/SkillSpector/` is the security scanner**, not a service. Don't run
  it as a service.

## Verification Loop

When you use the Edit or Write tool to modify source code, configuration, or
schema, verify the change before presenting it:

1. **Identify the service** the changed file belongs to.
2. **If the service has a test command** (see table above), run it from the
   service directory. If only specific tests are affected, scope the run.
3. **If the service has a build command but no tests** (e.g., `store/storefront`),
   run the build.
4. **If the service has neither** (e.g., `studio/ai-gateway` until it's
   scaffolded), say so explicitly in your response: "no test runner for this
   service; verified by reading the diff."
5. **If the command fails or returns non-zero:** read the output, fix the
   code, re-run. Don't present failing output to the user as done.

**Scope the rule, don't over-fire:**

- Doc-only edits (`*.md`), config comments, CLAUDE.md itself, README updates,
  and `git/` hook script content do **not** trigger the verification loop.
- A typo fix in a comment does not require running the full test suite.
- When in doubt, prefer the cheapest check that catches the change
  (single-file test > full suite > build > manual smoke).

**Forbidden shortcuts:**

- Don't present code as done if the test command exited non-zero.
- Don't say "tests pass" without running them.
- Don't suppress or `--no-verify` past failures to ship faster — fix the
  underlying issue.
- Don't claim a service runs if its `package.json` is missing.

## Security firewall

Pre-commit (`D:\pird\.pre-commit-config.yaml`) and GitHub Actions
(`D:\pird\.github/workflows/security.yml`) block on semgrep + trivy + osv-scanner
findings. If a commit is blocked, the finding is real or a rule needs narrowing —
don't bypass with `--no-verify`.

## Test-Driven Development

You must follow strict Test-Driven Development. Before writing any feature
code, you must write a failing test (RED). You will then run the test to
verify it fails. Only then are you authorized to write the minimal
implementation code to make it pass (GREEN), followed by refactoring.

**Exception:** You are authorized to write non-test code first only to
bootstrap the initial testing infrastructure if it does not exist (e.g.,
scaffolding `package.json`, installing pytest, adding a `jest.config.js`,
creating the first test file). Once a test runner exists for a service,
the strict RED-GREEN-REFACTOR cycle applies to every subsequent change
in that service.

**Service test-runner map** (matches the PostToolUse hook):

| Path | Test runner |
|---|---|
| `store/backend/**` | `yarn test:unit --watchAll=false` |
| `store/storefront/**` | `yarn build` (no test runner installed) |
| `studio/dubbing/**` | `pytest -x` |
| anything else | no auto-run; verify manually |

## Brand & memory

- Brand rules live in `BRAND.md` and the `pird-brand-checklist` memory item.
- Unresolved auth scheme between internal services is in the
  `pird-service-auth-decision` memory item — pick a scheme before any prod
  cross-service call.

## Output formatting: caveman mode

- Strip conversational fluff, polite preambles, greetings, articles, filler.
- Telegraphic, high-signal statements.
- **EXCEPTION:** code blocks, diffs, terminal commands, file paths, error stack traces stay 100% byte-for-byte precise. No compression.
- **SAFETY BREAK:** destructive ops, unverified security vulns, critical pipeline failures → drop caveman, full explicit text.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
