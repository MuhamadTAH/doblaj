#!/usr/bin/env python3
"""
Read-only static audit of a Supabase project, for Phase 1 of the
supabase-to-convex-migration skill.

Scans SQL migrations/schema files and Supabase Edge Functions under
<project-root>, and optionally frontend source, for the artifacts Phase 2
needs to translate. Never modifies anything on disk, never makes a network
or database call, and never prints environment variable *values* -- only
names -- since this report is meant to be safe to paste into a chat or a
ticket.

Usage:
    python3 audit_supabase_project.py <project-root> [--frontend-src PATH] [--out FILE.md]

Example:
    python3 audit_supabase_project.py ~/code/my-app --frontend-src ~/code/my-app/src
"""

import argparse
import re
import sys
from pathlib import Path

EXCLUDE_DIR_NAMES = {".git", "node_modules", ".next", "dist", "build", "__pycache__", ".turbo"}

SQL_PATTERNS = {
    "tables": re.compile(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?"?(\w+)"?', re.IGNORECASE),
    "foreign_keys": re.compile(r'REFERENCES\s+"?(\w+)"?', re.IGNORECASE),
    "unique_constraints": re.compile(r'\bUNIQUE\b', re.IGNORECASE),
    "check_constraints": re.compile(r'\bCHECK\s*\(', re.IGNORECASE),
    "db_defaults": re.compile(r'\bDEFAULT\b', re.IGNORECASE),
    "rls_enabled": re.compile(r'ENABLE ROW LEVEL SECURITY', re.IGNORECASE),
    "policies": re.compile(r'CREATE POLICY\s+"?([\w\s]+?)"?\s+ON\s+"?(\w+)"?', re.IGNORECASE),
    "triggers": re.compile(r'CREATE(?:\s+OR\s+REPLACE)?\s+TRIGGER\s+"?(\w+)"?', re.IGNORECASE),
}

FRONTEND_PATTERNS = {
    "table_reads (.from)": re.compile(r'(?<!\.storage)\.from\(\s*[\'"](\w+)[\'"]'),
    "realtime_channels (.channel)": re.compile(r'\.channel\(\s*[\'"]([^\'"]+)[\'"]'),
    "auth_calls (supabase.auth.*)": re.compile(r'supabase\.auth\.\w+'),
    "storage_calls (.storage.from)": re.compile(r'\.storage\.from\(\s*[\'"](\w+)[\'"]'),
    "rpc_calls (.rpc)": re.compile(r'\.rpc\(\s*[\'"](\w+)[\'"]'),
    "client_init (createClient)": re.compile(r'createClient\('),
}

ENV_VAR_NAME = re.compile(r'^\s*([A-Z][A-Z0-9_]*)\s*=')

MAX_EXAMPLES_PER_CATEGORY = 15


def iter_files(root: Path, extensions):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in extensions:
            continue
        if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except OSError:
        return ""


def scan_sql(root: Path):
    files = list(iter_files(root, {".sql"}))
    hits = {key: [] for key in SQL_PATTERNS}
    for f in files:
        text = read_text(f)
        rel = f.relative_to(root)
        for key, pattern in SQL_PATTERNS.items():
            for m in pattern.finditer(text):
                hits[key].append(f"{rel}: {m.group(0).strip()[:80]}")
    return files, hits


def scan_edge_functions(root: Path):
    fn_dir = root / "supabase" / "functions"
    if not fn_dir.exists():
        return []
    return sorted(p.name for p in fn_dir.iterdir() if p.is_dir() and not p.name.startswith("_"))


def scan_frontend(src_root: Path):
    files = list(iter_files(src_root, {".ts", ".tsx", ".js", ".jsx"}))
    hits = {key: [] for key in FRONTEND_PATTERNS}
    for f in files:
        text = read_text(f)
        rel = f.relative_to(src_root)
        for key, pattern in FRONTEND_PATTERNS.items():
            for m in pattern.finditer(text):
                hits[key].append(f"{rel}: {m.group(0).strip()}")
    return files, hits


def scan_env_var_names(root: Path):
    names = set()
    for envfile in root.rglob(".env*"):
        if not envfile.is_file() or any(part in EXCLUDE_DIR_NAMES for part in envfile.parts):
            continue
        for line in read_text(envfile).splitlines():
            m = ENV_VAR_NAME.match(line)
            if m:
                names.add(m.group(1))
    return sorted(names)


def cap(items):
    items = sorted(set(items))
    shown = items[:MAX_EXAMPLES_PER_CATEGORY]
    remainder = len(items) - len(shown)
    return shown, remainder


def render_report(root, sql_files, sql_hits, edge_fns, frontend_info, env_names, frontend_src_arg):
    lines = []
    lines.append(f"# Supabase audit: `{root}`\n")
    lines.append(
        "Static, read-only scan. This seeds Phase 1 -- it is a starting inventory, "
        "not a substitute for reading the flagged files. Env var *values* were never read, only names.\n"
    )

    lines.append("## SQL schema\n")
    lines.append(f"Scanned {len(sql_files)} `.sql` file(s).\n")
    if not sql_files:
        lines.append(
            "No `.sql` files found under this root. If migrations live elsewhere "
            "(e.g. a separate `supabase/` repo, or a Supabase-hosted-only project "
            "with no local migration files), dump the schema first with "
            "`supabase db dump --schema public -f schema.sql` and re-run this script "
            "against that file's directory.\n"
        )
    else:
        for key in ["tables", "foreign_keys", "unique_constraints", "check_constraints",
                    "db_defaults", "rls_enabled", "policies", "triggers"]:
            shown, remainder = cap(sql_hits[key])
            label = key.replace("_", " ")
            lines.append(f"**{label}** ({len(set(sql_hits[key]))} unique match(es))")
            if shown:
                lines.extend(f"- {s}" for s in shown)
                if remainder > 0:
                    lines.append(f"- ...and {remainder} more")
            else:
                lines.append("- none found")
            lines.append("")

    lines.append("## Edge Functions\n")
    if edge_fns:
        lines.append(f"Found {len(edge_fns)} function(s) under `supabase/functions/`:")
        lines.extend(f"- {name} -- **check: does this call an external API?**" for name in edge_fns)
    else:
        lines.append("No `supabase/functions/` directory found.")
    lines.append("")

    lines.append("## Frontend Supabase usage\n")
    if frontend_src_arg is None:
        lines.append("No `--frontend-src` passed -- skipped. Re-run with `--frontend-src <path>` to scan the frontend.\n")
    else:
        files, hits = frontend_info
        lines.append(f"Scanned {len(files)} frontend file(s) under `{frontend_src_arg}`.\n")
        for key, matches in hits.items():
            shown, remainder = cap(matches)
            lines.append(f"**{key}** ({len(set(matches))} unique match(es))")
            if shown:
                lines.extend(f"- {s}" for s in shown)
                if remainder > 0:
                    lines.append(f"- ...and {remainder} more")
            else:
                lines.append("- none found")
            lines.append("")

    lines.append("## Environment variable names (values never read)\n")
    if env_names:
        lines.extend(f"- {name}" for name in env_names)
    else:
        lines.append("No `.env*` files found under this root.")
    lines.append("")

    lines.append("## Not covered by this script -- check by hand (see supabase-audit-checklist.md)\n")
    lines.append("- Auth provider configuration and enabled login methods")
    lines.append("- Storage bucket access policies (public vs. RLS-gated)")
    lines.append("- `ON DELETE` behavior on foreign keys (e.g. `CASCADE`)")
    lines.append("- Full-text search (`to_tsvector`/`to_tsquery`) and aggregate/window queries")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project_root", help="Path to the Supabase project root")
    parser.add_argument("--frontend-src", default=None, help="Optional path to frontend source to scan for Supabase client usage")
    parser.add_argument("--out", default=None, help="Write the Markdown report to this file instead of stdout")
    args = parser.parse_args()

    root = Path(args.project_root).expanduser().resolve()
    if not root.exists():
        print(f"Error: {root} does not exist", file=sys.stderr)
        sys.exit(1)

    sql_files, sql_hits = scan_sql(root)
    edge_fns = scan_edge_functions(root)

    frontend_info = ([], {key: [] for key in FRONTEND_PATTERNS})
    if args.frontend_src:
        src_root = Path(args.frontend_src).expanduser().resolve()
        if not src_root.exists():
            print(f"Warning: --frontend-src {src_root} does not exist, skipping frontend scan", file=sys.stderr)
            args.frontend_src = None
        else:
            frontend_info = scan_frontend(src_root)

    env_names = scan_env_var_names(root)

    report = render_report(root, sql_files, sql_hits, edge_fns, frontend_info, env_names, args.frontend_src)

    if args.out:
        Path(args.out).write_text(report)
        print(f"Wrote report to {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
