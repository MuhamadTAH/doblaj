# Project Agent Team — Setup Guide

[![Security](https://github.com/OWNER/REPO/actions/workflows/security.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/security.yml)

This is a complete Claude Code subagent team for the dubbing + store + bots project: 8 specialized agents, each preloaded with a SKILL.md containing the architecture decisions, code patterns, and checklists for its domain — plus persistent memory so nothing gets re-explained every session.

## Installation

Copy the `.claude/` folder into the root of your project repository:

```
your-project/
├── .claude/
│   ├── agents/        ← 8 subagent definitions
│   └── skills/        ← 8 domain reference docs (SKILL.md each)
├── store/
│   ├── backend/       ← Medusa backend
│   └── storefront/    ← Next.js storefront
├── studio/
│   ├── ai-gateway/    ← AI Gateway service
│   ├── bot-bridge/    ← Chatwoot bridge service
│   ├── comment-bot/   ← FB/IG comment bot service
│   ├── dubbing/       ← Audio/video dubbing service
│   ├── tts-service/   ← TTS service
│   └── chatwoot/      ← Chatwoot deployment compose
└── ... (your actual project code)
```

Commit `.claude/` to version control — these are project subagents, meant to be shared with anyone (including future-you, or your AI dev) working on this repo. Restart your Claude Code session after adding these files so they're loaded.

## How This Works

Two Claude Code primitives, used together:

- **Skills** (`.claude/skills/<name>/SKILL.md`) are portable domain knowledge — architecture decisions, API contracts, checklists. They can be loaded into any agent's context.
- **Subagents** (`.claude/agents/<name>.md`) are specialized workers with their own context window, tool access, and model. Each one here preloads its matching skill via the `skills:` field, so it starts every task already knowing the relevant architecture.

Each agent also has `memory: project`, giving it a persistent `MEMORY.md` under `.claude/agent-memory/<agent-name>/` that survives across sessions — this is where "don't forget anything" actually lives mechanically: each agent writes down decisions, gotchas, and learnings as it works, and reads them back in next time.

## The 8 Agents

| Agent | Role | Model |
|---|---|---|
| `architect` | Coordinates everything — service boundaries, shared DB schema, cross-service contracts, READMEs | opus |
| `store-builder` | Medusa.js store, Next.js storefront, AI store agent (admin tools + chat widget) | sonnet |
| `bot-builder` | Chatwoot DM bots (Telegram/FB/IG) + separate FB/IG comment handler | sonnet |
| `dubbing-engineer` | Kurdish Sorani → Iraqi Arabic dubbing pipeline (Demucs, Gemini, MiniMax, FFmpeg) | sonnet |
| `ai-gateway-builder` | Shared AI gateway — every other service's only path to Claude/Gemini/MiniMax | sonnet |
| `security-auditor` | Read-only security review — threat-modeling methodology, real-world breach patterns, AI prompt-injection focus | opus |
| `debugger` | Cross-service bug investigation and fixes | sonnet |
| `devops-deployer` | Railway deployment, env vars, domain routing | sonnet |

## How to Use Them

Claude Code delegates automatically based on each agent's `description` field — for most requests you can just describe the task and the right agent picks it up. To be explicit:

```
Use the dubbing-engineer agent to add retry logic for failed translation chunks
@"security-auditor (agent)" review the new bot webhook before we deploy
Use the architect agent to figure out where the dubbing-job-status webhook should live
```

For a full security pass before a deploy:
```
Use the security-auditor agent to review all services against the security-engineering skill
```

## Coverage Map — "No Gaps" Check

Every major decision from project planning maps to exactly one (or two) agents below. If a new task doesn't fit any row, that's the signal to ask `architect` where it belongs — not to skip it.

| Area | Agent(s) |
|---|---|
| Monorepo structure, two-domain split (`mysite.com` / `studio.mysite.com`) | `architect`, `devops-deployer` |
| Shared Supabase schema & RLS | `architect` (schema), `security-auditor` (RLS) |
| HTTP-only contract between services | `architect` (enforces), all builders (follow) |
| Medusa store, digital products, storefront | `store-builder` |
| AI store admin agent (create_product, refunds, etc.) | `store-builder` + `ai-gateway-builder` |
| Telegram/FB/IG DM bots via Chatwoot | `bot-builder` |
| FB/IG public comment auto-replies | `bot-builder` |
| Video dubbing pipeline (separation → ASR → translation → TTS → reassembly) | `dubbing-engineer` |
| TTS provider choice & licensing (Fish Audio API) | `dubbing-engineer` |
| Shared AI gateway, system prompts, cost logging | `ai-gateway-builder` |
| API keys, .env, rate limiting/cost control, webhooks, IDOR, SSRF, file uploads, AI prompt-injection & tool-use safety | `security-auditor` |
| Railway services, env vars, domains | `devops-deployer` |
| Any bug, in any service | `debugger` |

## Keeping This Up to Date

As the project evolves:
- New service or table → `architect` updates `project-architecture` SKILL.md and this README's tables
- New AI capability → `ai-gateway-builder` updates `ai-gateway` SKILL.md's endpoint/context tables
- New security pattern, incident, or gap-hunting finding → `security-auditor` adds it to `security-engineering` SKILL.md (Section 3 for new vulnerability categories, Section 6 stays the evergreen framework)
- Recurring bug class discovered → `debugger` adds it to `debugging-playbook` SKILL.md's "Known Gotchas"

Skills are the shared, versioned knowledge; agent memory (`.claude/agent-memory/`) is each agent's personal running notes. If something belongs in both, put the stable/general version in the skill and let memory hold the specific, evolving details (current status, recent decisions, things still in progress).
