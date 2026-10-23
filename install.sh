#!/usr/bin/env bash
# ============================================================================
# SMP — Structural Memory Protocol installer
#
#   One line:
#     curl -fsSL https://raw.githubusercontent.com/offx-zinth/SMP/main/install.sh | bash
#
#   What it does:
#     1. Installs SMP into an isolated venv at ~/.smp (no sudo, no root writes)
#     2. Drops `smp` and `smp-mcp` launchers into ~/.local/bin
#     3. Wires up the SMP agent skill + MCP server — you choose the scope:
#          1) global  — user-wide: skill into ~/.agents, ~/.claude,
#             ~/.config/opencode, ~/.codex + MCP server into any detected
#             harness config (Claude Code, OpenCode, Codex, Cursor, Gemini
#             CLI, Windsurf, VS Code, Claude Desktop)     [default]
#          2) local   — this repo only: ./.mcp.json, ./opencode.json,
#             ./.cursor/mcp.json, ./.gemini/settings.json, skill into
#             ./.agents and ./.claude
#     4. The graph itself is ALWAYS per-repo: one .smp/graph.smpg per project,
#        auto-ingested on first use.
#
#   Options:
#     --uninstall        remove everything installed above
#     --global / --local wiring scope (skips the interactive question)
#     --scope <global|local>   same as --global / --local
#     --skip-skills      do not install SKILL.md copies
#     --skip-mcp         do not touch any harness MCP config
#     --all-harnesses    register MCP even for harnesses not detected on disk
#     --add-path         append ~/.local/bin to your shell rc (idempotent)
#     --dir <path>       install root    (default ~/.smp)
#     --bin-dir <path>   launcher dir    (default ~/.local/bin)
#     --ref <ref>        install a branch/tag instead of main (default main)
#     --help             this message
#
#   The script is idempotent — rerun to upgrade. It reads one answer from
#   /dev/tty when a terminal is attached (works under `curl | bash`);
#   non-interactive runs default to global wiring. Never writes outside
#   ~/.smp, ~/.local/bin, or the requested scope's config dirs.
#
#   Config safety guarantees:
#     • EXISTING harness configs are only ever edited to ADD a missing `smp`
#       entry. An `smp` entry you wrote yourself (different path, custom args,
#       custom env) is left untouched, with a note.
#     • A timestamped backup (.smp-bak-*) is written next to any file before
#       the first modification.
#     • Unparseable/JSONC files are detected and skipped instead of rewritten.
#     • Codex TOML blocks are appended between >>> <<< markers and validated
#       with tomllib (rolled back on parse failure).
#     • `--uninstall` removes only entries pointing at the path being removed.
#
#   License: MIT (offx-zinth/SMP)
# ============================================================================

set -Eeuo pipefail
IFS=$' \t\n'

# ---------------------------------------------------------------- pretty logs
# All display helpers write to stderr — several functions run inside
# command substitution, so stdout must stay reserved for return values.
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; RESET=""
fi
say()  { printf '%s\n' "  $*" >&2; }
step() { printf '%s %s\n' "${BOLD}${CYAN}►" "${RESET}${1}" >&2; }
ok()   { printf '%s %s\n' "${GREEN}✔" "${RESET}${1}" >&2; }
warn() { printf '%s %s\n' "${YELLOW}▲" "${RESET}${1}" >&2; }
die()  { printf '%s %s\n' "${RED}✖ ERROR:" "${RESET}${1}" >&2
         say "  help / issues: ${REPO_URL}" >&2
         exit 1; }

usage() {
  awk 'NR>2 && /^# =+$/ {exit} NR>2 {sub(/^#( )?/,""); print}' "$0"
}

# ------------------------------------------------------------------- settings
REPO_SLUG="${SMP_REPO_SLUG:-offx-zinth/SMP}"
REPO_URL="https://github.com/${REPO_SLUG}"
SMPSYS="${SMP_DIR:-$HOME/.smp}"
BINDIR="${SMP_BIN_DIR:-$HOME/.local/bin}"
REF="${SMP_REF:-main}"
STAMPFILE="$SMPSYS/installed.json"

DO_UNINSTALL=0; SKIP_SKILLS=0; SKIP_MCP=0; ALL_HARNESS=0; ADD_PATH=0
SCOPE=""   # "global" (user-wide wiring) | "local" (current repo only)

if [ $# -gt 0 ]; then
  case "$1" in
    -h|--help|-V|--version) usage; exit 0 ;;
  esac
fi
while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall)     DO_UNINSTALL=1 ;;
    --skip-skills)   SKIP_SKILLS=1 ;;
    --skip-mcp)      SKIP_MCP=1 ;;
    --all-harnesses) ALL_HARNESS=1 ;;
    --add-path)      ADD_PATH=1 ;;
    --local)         SCOPE=local ;;
    --global)        SCOPE=global ;;
    --scope)         case "${2:-}" in
                       global|local) SCOPE="$2"; shift ;;
                       *) die "--scope needs 'global' or 'local'" ;;
                     esac ;;
    --dir)           SMPSYS="${2:?--dir needs a value}"; shift ;;
    --bin-dir)       BINDIR="${2:?--bin-dir needs a value}"; shift ;;
    --ref)           REF="${2:?--ref needs a value}"; shift ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

VENVDIR="$SMPSYS/venv"
SRCDIR="$SMPSYS/src"
LIBDIR="$SMPSYS/lib"

cleanup_tmp() {
  if [ -n "${TMP_SMP_DIR:-}" ]; then rm -rf "$TMP_SMP_DIR"; TMP_SMP_DIR=""; fi
  if [ -n "${EXCLUDE_FILE:-}" ] && [ -f "$EXCLUDE_FILE" ]; then rm -f "$EXCLUDE_FILE"; EXCLUDE_FILE=""; fi
}
on_exit() { cleanup_tmp; }
trap on_exit EXIT
trap 'exit 130' INT TERM

die_no_python() {
  die "no Python >= 3.11 found. Install it first:
    Ubuntu/Debian:  sudo apt install -y python3
    macOS:          brew install python@3.11
    Any OS (uv):    curl -LsSf https://astral.sh/uv/install.sh | sh
  SMP requires CPython >= 3.11 (pyproject requires-python)."
}

# macOS bash 3.2 safe: no mapfile, no assoc arrays, no ${var,,}
find_python() {
  local _i
  for _i in python3.11 python3.12 python3.13 python3; do
    command -v "$_i" >/dev/null 2>&1 || continue
    if "$_i" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
      command -v "$_i"
      return 0
    fi
  done
  return 1
}

pick_py_for_helpers() {
  if [ -x "$VENVDIR/bin/python" ]; then printf '%s' "$VENVDIR/bin/python"; return 0; fi
  command -v python3 >/dev/null 2>&1 || die "python3 required for config editing"
  printf 'python3'
}

# ---------------------------------------------------------------- source tree
write_excludes() {
  EXCLUDE_FILE="$SMPSYS/.install-excludes"
  cat > "$EXCLUDE_FILE" <<'EOF'
.git
.venv
venv
.smp
node_modules
__pycache__
*.py[cod]
*.egg-info
dist
build
htmlcov
.coverage
.mypy_cache
.pytest_cache
*.deb
*.tar.gz
*.zip
Qwen3-Embedding-0.6B-GGUF
runs
chroma
EOF
}

sync_tree() {  # $1 = source dir → copies into $SRCDIR without junk
  write_excludes
  mkdir -p "$SRCDIR"
  (cd "$1" && tar --exclude-from="$EXCLUDE_FILE" -cf - .) | (cd "$SRCDIR" && tar -xf -)
}

fetch_tarball() {
  local url
  if [ -n "${SMP_TARBALL_URL:-}" ]; then
    url="$SMP_TARBALL_URL"
  else
    url="https://codeload.github.com/${REPO_SLUG}/tar.gz/${REF}"
  fi
  TMP_SMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/smp-install.XXXXXX")"
  step "downloading SMP source (ref: $REF)"
  curl -fsSL --retry 3 --retry-delay 2 -o "$TMP_SMP_DIR/src.tar.gz" "$url" \
    || die "download failed: $url"
  tar -xzf "$TMP_SMP_DIR/src.tar.gz" -C "$TMP_SMP_DIR" \
    || die "extract failed (corrupted download?)"
  local extracted
  extracted="$(find "$TMP_SMP_DIR" -maxdepth 1 -type d -name 'SMP-*' | head -n 1)"
  [ -n "$extracted" ] || die "unexpected tarball layout (expected SMP-*/)"
  printf '%s' "$extracted"
}

detect_local_repo() {
  # `bash install.sh` invoked inside a real SMP checkout → use that source.
  local dir=""
  if [ -n "${SMP_LOCAL_SRC:-}" ]; then printf '%s' "$SMP_LOCAL_SRC"; return 0; fi
  if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
  fi
  if [ -n "$dir" ] && [ -f "$dir/pyproject.toml" ] \
     && grep -q '^name *= *"smp"' "$dir/pyproject.toml" 2>/dev/null \
     && [ -f "$dir/smp/cli.py" ]; then
    printf '%s' "$dir"; return 0
  fi
  return 1
}

# --------------------------------------------------------------------- python
ensure_python() {
  local py
  py="$(find_python)" && { command -v "$py"; return 0; }
  warn "no Python 3.11+ on PATH — bootstrapping uv-managed Python (user space, no sudo)"
  local uvbin="$HOME/.local/bin/uv"
  if [ ! -x "$uvbin" ] && ! command -v uv >/dev/null 2>&1; then
    step "installing uv (astral.sh)"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || die_no_python
  fi
  command -v uv >/dev/null 2>&1 && uvbin="$(command -v uv)"
  "$uvbin" python install --no-progress 3.11 >/dev/null 2>&1 || true
  py="$("$uvbin" python find 3.11 2>/dev/null || true)"
  if [ -z "$py" ]; then
    "$uvbin" python install --no-progress 3.12 >/dev/null 2>&1 || true
    py="$("$uvbin" python find 3.12 2>/dev/null || true)"
  fi
  [ -n "$py" ] || die_no_python
  printf '%s' "$py"
}

add_path_rc() {
  case ":${PATH:-}:" in *":${BINDIR}:"*) ok "PATH already covers $BINDIR"; return 0 ;; esac
  local rc_list="" rc
  for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
    [ -f "$rc" ] && rc_list="$rc_list $rc"
  done
  if [ -z "$rc_list" ]; then
    rc="$HOME/.profile"
    : > "$rc" 2>/dev/null || die "cannot create $rc"
    rc_list="$rc"
  fi
  for rc in $rc_list; do
    if grep -qE '\.local/bin' "$rc" 2>/dev/null; then
      ok "PATH entry for ~/.local/bin already in $rc"
      return 0
    fi
  done
  local target="" mt newest=0
  for rc in $rc_list; do
    mt=$(stat -c %Y "$rc" 2>/dev/null || stat -f %m "$rc" 2>/dev/null || echo 0)
    if [ "$mt" -ge "$newest" ]; then newest=$mt; target=$rc; fi
  done
  { echo ''; echo '# added by SMP installer'; echo "export PATH=\"$BINDIR:\$PATH\""; } >> "$target"
  ok "added PATH line to $target — open a new shell or: exec \$SHELL -l"
}

# --------------------------------------------------- harness config registry
# JSON configs are merged (never clobbered). Backups are written next to the
# file before every modification. stdlib-only python — runs on any python3.
merge_mcp() {  # merge_mcp <mode> <file> <command-path> <add|remove>
  local mode="$1" file="$2" cmd="$3" action="$4"
  local py3
  py3="$(pick_py_for_helpers)"
  SMP_MODE="$mode" SMP_FILE="$file" SMP_CMD="$cmd" SMP_ACTION="$action" \
  SMP_CREATED_LIST="$SMPSYS/lib/created-configs.lst" SMP_SCOPE_TAG="$SCOPE" \
    "$py3" <<'PYMERGE' || return 1
import json, os, shutil, sys, time

mode = os.environ["SMP_MODE"]
path = os.path.abspath(os.path.expanduser(os.environ["SMP_FILE"]))
cmd = os.environ["SMP_CMD"]
action = os.environ["SMP_ACTION"]

KEY = {"opencode": "mcp", "vscode": "servers"}.get(mode, "mcpServers")

cfg, state = {}, "new"
if os.path.exists(path):
    raw = open(path).read().strip()
    if raw:
        try:
            cfg = json.loads(raw)
        except Exception as e:
            print(f"  skip {path}: unparseable ({e}) — left untouched")
            sys.exit(1)
    state = "loaded"
if not isinstance(cfg, dict):
    print(f"  skip {path}: root is not a JSON object — left untouched")
    sys.exit(1)

bucket = cfg.setdefault(KEY, {})
if not isinstance(bucket, dict):
    print(f"  skip {path}: '{KEY}' is not an object — left untouched")
    sys.exit(1)

if mode == "opencode":
    entry = {"type": "local", "command": [cmd]}
elif mode == "vscode":
    entry = {"type": "stdio", "command": cmd, "args": [], "env": {}}
else:
    entry = {"command": cmd, "args": [], "env": {}}

created_list = os.environ.get("SMP_CREATED_LIST", "")
scope_tag = os.environ.get("SMP_SCOPE_TAG", "global")

if action == "add":
    existing = bucket.get("smp")
    if existing is None:
        bucket["smp"] = entry
        verb = "registered"
        if created_list and state == "new":
            try:
                os.makedirs(os.path.dirname(created_list) or ".", exist_ok=True)
                with open(created_list, "a") as reg:
                    reg.write(f"{scope_tag}\t{path}\n")
            except OSError:
                pass
    elif existing == entry:
        print(f"  {path}: already up to date")
        sys.exit(0)
    else:
        def _cmd_path(e):
            c = e.get("command") if isinstance(e, dict) else None
            if isinstance(c, list):
                c = c[0] if c else None
            return c if isinstance(c, str) else None
        ex = _cmd_path(existing) or ""
        ours = entry["command"] if isinstance(entry.get("command"), str) else cmd
        ours = ours if isinstance(ours, str) else cmd
        if ex == ours:
            print(f"  {path}: existing smp entry has custom args/env — left untouched")
        elif os.path.basename(ex) == "smp-mcp":
            print(f"  {path}: smp entry points at another install ({ex}) — left untouched")
        else:
            print(f"  {path}: user-authored smp entry found — left untouched")
        print("    (delete it manually if you want the installer's own entry; configs are never overwritten)")
        if state == "loaded":
            pass  # untouched
        sys.exit(0)
else:
    existing = bucket.get("smp")
    if existing is None:
        print(f"  {path}: no smp entry")
        sys.exit(0)
    def _cmd_path(e):
        c = e.get("command") if isinstance(e, dict) else None
        if isinstance(c, list):
            c = c[0] if c else None
        return c if isinstance(c, str) else None
    ex = _cmd_path(existing) or ""
    if ex != cmd:
        print(f"  {path}: smp entry points at {ex or '(unknown)'} — left untouched")
        sys.exit(0)
    del bucket["smp"]
    if not bucket:
        cfg.pop(KEY, None)
    verb = "removed"

if state == "loaded":
    bak = f"{path}.smp-bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, bak)
    print(f"  backup: {bak}")
else:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print(f"  {path}: {verb}")
PYMERGE
}

register_codex_toml() {  # register_codex_toml <file> <0=add | 1=remove>
  local file="${1:-$HOME/.codex/config.toml}" action="${2:-0}"
  local m_begin m_end
  m_begin='# >>> smp-mcp (added by SMP install.sh) >>>'
  m_end='# <<< smp-mcp (added by SMP install.sh) <<<'

  if [ "$action" = "1" ]; then
    if [ -f "$file" ] && grep -qF "$m_begin" "$file" 2>/dev/null; then
      local bak="$file.smp-bak-$(date +%Y%m%d-%H%M%S)"
      cp "$file" "$bak"
      awk -v b="$m_begin" -v e="$m_end" '
        index($0, b) { skip = 1; next }
        skip && index($0, e) { skip = 0; next }
        !skip { print }' "$file" > "$file.tmp" \
        && mv "$file.tmp" "$file" \
        || { rm -f "$file.tmp"; warn "could not clean $file — handled manually"; return 1; }
      say "  backup: $bak"
      say "  $file: installer-managed block removed"
    elif [ -f "$file" ] && grep -qE '^\[mcp_servers\.smp\]' "$file" 2>/dev/null; then
      say "  $file: [mcp_servers.smp] exists but was not written by the installer — left untouched"
    fi
    return 0
  fi

  if [ ! -f "$file" ]; then
    mkdir -p "$(dirname "$file")" 2>/dev/null || true
    : > "$file" || die "cannot create $file"
  fi
  if grep -qF "$m_begin" "$file" 2>/dev/null; then
    if grep -qF "\"$BINDIR/smp-mcp\"" "$file" 2>/dev/null; then
      say "  $file: already registered"
      return 0
    fi
    say "  $file: exists as installer block but points elsewhere — left untouched"
    return 0
  fi
  if grep -qE '^\[mcp_servers\.smp\]' "$file" 2>/dev/null; then
    say "  $file: user-authored [mcp_servers.smp] found — left untouched"
    say "    (delete that block manually if you want the installer's own entry)"
    return 0
  fi

  local bak=""
  if [ -s "$file" ]; then
    bak="$file.smp-bak-$(date +%Y%m%d-%H%M%S)"
    cp "$file" "$bak"
  fi
  {
    printf '\n%s\n' "$m_begin"
    printf '%s\n' '[mcp_servers.smp]'
    printf '%s\n' "command = \"$BINDIR/smp-mcp\""
    printf '%s\n' "$m_end"
  } >> "$file" || die "cannot write $file"

  # validate the resulting TOML; roll back on any parse failure
  local py3
  py3="$(pick_py_for_helpers)"
  if ! "$py3" - "$file" <<'PYTOML' 2>/dev/null; then
import sys
try:
    import tomllib
except ImportError:
    sys.exit(0)
with open(sys.argv[1], "rb") as f:
    tomllib.load(f)
PYTOML
    if [ -n "$bak" ]; then
      cp "$bak" "$file"
      warn "TOML validation failed after edit — $file restored from backup; add the block manually"
    else
      warn "TOML validation failed — verify $file"
    fi
    return 1
  fi
  say "  $file: smp block added (TOML validated)"
  return 0
}

# ------------------------------------------------------------------ locations
# Skill/MCP wiring targets depend on the resolved scope (global vs local).
# Configured by set_targets() in main() after the scope is known.
SKILL_TARGETS=""
REPO_ROOT=""

set_targets() {
  if [ "$SCOPE" = "global" ]; then
    SKILL_TARGETS="
$HOME/.agents/skills/smp
$HOME/.claude/skills/smp
$HOME/.config/opencode/skills/smp
$HOME/.codex/skills/smp
"
  else
    SKILL_TARGETS="
$REPO_ROOT/.agents/skills/smp
$REPO_ROOT/.claude/skills/smp
"
  fi
}

resolve_repo_root() {
  if [ -n "${SMP_REPO_ROOT:-}" ]; then printf '%s' "$SMP_REPO_ROOT"; return 0; fi
  local root
  if command -v git >/dev/null 2>&1; then
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    [ -n "$root" ] && { printf '%s' "$root"; return 0; }
  fi
  printf '%s' "$PWD"
}

ask_scope() {
  # Decided by: --local/--global/--scope flag, or SMP_SCOPE env, else a
  # /dev/tty prompt (works under `curl | bash` in an interactive terminal);
  # with no tty (CI/pipes) default to global with a printed notice.
  if [ -n "$SCOPE" ]; then return 0; fi   # explicit flag wins — never reprompt
  if [ -n "${SMP_SCOPE:-}" ]; then
    case "$SMP_SCOPE" in
      global|local) SCOPE="$SMP_SCOPE"; return 0 ;;
      *) warn "SMP_SCOPE='$SMP_SCOPE' not understood — falling back to the prompt" ;;
    esac
  fi
  SCOPE=global
  if ! is_readable_tty; then
    say "  non-interactive run (no /dev/tty) — defaulting to ${BOLD}GLOBAL${RESET} wiring."
    say "  repo-only wiring: rerun inside the repo with --local"
    return 0
  fi
  local reply tries
  for tries in 1 2 3; do
    printf '\n%s\n' "  Where should SMP be wired up?" >&2
    printf '%s\n'   "    1) ${BOLD}global${RESET}  — agent harnesses across this machine (user-level configs)" >&2
    printf '%s\n'   "    2) ${BOLD}local${RESET}   — only the current repo (./.mcp.json, ./opencode.json, ./ .agents skills)" >&2
    printf '%s'     "  choose [1/2] (default 1): " >&2
    if ! IFS= read -r reply < /dev/tty 2>/dev/null; then
      say "  (no answer — defaulting to global)"
      return 0
    fi
    case "$reply" in
      ""|"1"|g|G|[Gg]lobal) SCOPE=global; return 0 ;;
      "2"|l|L|[Ll]ocal)     SCOPE=local;  return 0 ;;
      *) printf '  invalid answer: %s\n' "$reply" >&2 ;;
    esac
  done
  say "  giving up on the prompt — defaulting to global"
  return 0
}

is_readable_tty() {
  # real test: /dev/tty can actually be O_RDWR-opened (ENXIO when no
  # controlling terminal exists — e.g. CI or sandboxed shells)
  (exec 3<>/dev/tty) 2>/dev/null
}

install_skill_files() {
  local src="$1" dest found=0
  step "installing SMP agent skill (SKILL.md)"
  for dest in $SKILL_TARGETS; do
    if [ -f "$dest/SKILL.md" ] && ! grep -q "SMP-INSTALLER-MANAGED" "$dest/SKILL.md" 2>/dev/null; then
      local pre_bak="$dest/SKILL.md.smp-bak-$(date +%Y%m%d-%H%M%S)"
      cp "$dest/SKILL.md" "$pre_bak" 2>/dev/null \
        && say "  existing custom $dest/SKILL.md was NOT ours — backed up to $pre_bak before replacing"
    fi
    if mkdir -p "$dest" 2>/dev/null && cp -f "$src" "$dest/SKILL.md" 2>/dev/null \
       && printf '\n<!-- SMP-INSTALLER-MANAGED: refreshed by SMP install.sh; safe to delete with install.sh --uninstall -->\n' >> "$dest/SKILL.md"; then
      found=$((found + 1))
    else
      warn "could not install skill into $dest"
    fi
  done
  if [ "$SCOPE" = "global" ]; then
    say "  installed into $found locations (universal ~/.agents + Claude Code + OpenCode + Codex)"
  else
    say "  installed into $found repo locations (./.agents/skills/smp + ./.claude/skills/smp)"
  fi
  ok "agent skill ready — agents will discover how to use smp_* tools"
}

uninstall_skill_files() {
  local dest
  for dest in $SKILL_TARGETS; do
    rm -f "${dest%/}/SKILL.md" 2>/dev/null || true
    rmdir "${dest%/}" 2>/dev/null || true
  done
}

write_launchers() {
  step "creating launchers in $BINDIR"
  mkdir -p "$BINDIR" || die "cannot create $BINDIR"
  mkdir -p "$LIBDIR" || die "cannot create $LIBDIR"

  if [ -f "$SRCDIR/packaging/smp-mcp-launcher.py" ]; then
    cp -f "$SRCDIR/packaging/smp-mcp-launcher.py" "$LIBDIR/smp-mcp-launcher.py"
  else
    # older source trees (older --ref tags) may not ship the launcher file —
    # fall back to the copy embedded in the installer itself
    warn "packaging/ missing in source ref — writing launcher from installer fallback"
    cat > "$LIBDIR/smp-mcp-launcher.py" <<'LAUNCHER_PY'
#!/usr/bin/env python
"""SMP MCP launcher (embedded fallback — identical to packaging/smp-mcp-launcher.py)."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys


def project_root() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.getcwd()


def main() -> None:
    root = project_root()
    override = os.environ.get("SMP_GRAPH_PATH")
    if override:
        graph = override if os.path.isabs(override) else os.path.join(root, override)
    else:
        graph = os.path.join(root, ".smp", "graph.smpg")

    if not os.path.exists(graph) and os.environ.get("SMP_AUTO_INGEST", "1") != "0":
        print(f"smp-mcp: no graph at {graph}, ingesting {root} first...", file=sys.stderr)
        try:
            from smp.cli import ingest_directory

            stats = asyncio.run(ingest_directory(root, graph_path=graph))
            print(
                f"smp-mcp: ingested {stats['files']} files, "
                f"{stats['nodes']} nodes, {stats['errors']} errors",
                file=sys.stderr,
            )
        except Exception as exc:
            print(f"smp-mcp: auto-ingest failed ({exc}); serving empty graph", file=sys.stderr)

    os.environ["SMP_GRAPH_PATH"] = graph
    os.chdir(root)

    from smp.protocol.mcp import main as mcp_main

    mcp_main()


if __name__ == "__main__":
    main()
LAUNCHER_PY
  fi

  cat > "$BINDIR/smp" <<EOF
#!/usr/bin/env bash
# SMP CLI — generated by SMP install.sh
exec "$VENVDIR/bin/python" -m smp.cli "\$@"
EOF
  cat > "$BINDIR/smp-mcp" <<EOF
#!/usr/bin/env bash
# SMP MCP launcher — generated by SMP install.sh
exec "$VENVDIR/bin/python" "$LIBDIR/smp-mcp-launcher.py" "\$@"
EOF
  chmod +x "$BINDIR/smp" "$BINDIR/smp-mcp"
  ok "wrote $BINDIR/smp and $BINDIR/smp-mcp"
}

remove_created_files() {  # only deletes installer-CREATED files that are now empty
  local scope="$1" lst="$SMPSYS/lib/created-configs.lst"
  [ -f "$lst" ] || return 0
  local tag path deletable
  while IFS=$'\t' read -r tag path; do
    [ -z "$path" ] && continue
    if [ "$tag" != "$scope" ]; then continue; fi
    [ -f "$path" ] || continue
    deletable="$(python3 - "$path" <<'PYHOPE' 2>/dev/null || echo KEEP
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("KEEP"); sys.exit(0)
def empty_container(v):
    return isinstance(v, dict) and len(v) == 0
if d == {} or all(empty_container(v) for v in d.values()):
    print("DELETE")
else:
    print("KEEP")
PYHOPE
)"
    [ "$deletable" = "DELETE" ] || { say "  kept $path (has non-SMP content)"; continue; }
    rm -f "$path" && say "  removed installer-created file (now empty): $(basename "$path")"
  done < "$lst"
  # drop the now-stale registry entries of the removed files
  if [ "$scope" = "global" ]; then :; fi
  local tmpreg="$(mktemp "${TMPDIR:-/tmp}/smp-reg.XXXXXX")"
  awk -v s="$scope" -F'\t' '$1 != s {print}' "$lst" > "$tmpreg" && mv "$tmpreg" "$lst"
}

register_mcp_all() {  # register_mcp_all <add|remove>
  local action="$1"
  local cmd="$BINDIR/smp-mcp"
  local xdg="${XDG_CONFIG_HOME:-$HOME/.config}"

  local items=""
  if [ "$SCOPE" = "global" ]; then
    # user-wide configs — only when the harness exists on disk
    if [ "$ALL_HARNESS" = "1" ] || [ -d "$xdg/opencode" ];  then items="$items opencode:$xdg/opencode/opencode.json"; fi
    if [ "$ALL_HARNESS" = "1" ] || [ -d "$HOME/.claude" ];  then items="$items claude:$HOME/.claude.json"; fi
    if [ "$ALL_HARNESS" = "1" ] || [ -d "$HOME/.cursor" ];  then items="$items cursor:$HOME/.cursor/mcp.json"; fi
    if [ "$ALL_HARNESS" = "1" ] || [ -d "$HOME/.gemini" ];  then items="$items gemini:$HOME/.gemini/settings.json"; fi
    if [ "$ALL_HARNESS" = "1" ] || [ -d "$HOME/.codeium" ]; then items="$items windsurf:$HOME/.codeium/windsurf/mcp_config.json"; fi
    if [ "$ALL_HARNESS" = "1" ] || [ -d "$HOME/.codex" ];   then items="$items codex:$HOME/.codex/config.toml"; fi

    local vsdir="$HOME/.config/Code"
    [ "$(uname -s)" = "Darwin" ] && vsdir="$HOME/Library/Application Support/Code"
    if [ "$ALL_HARNESS" = "1" ] || [ -d "$vsdir" ]; then items="$items vscode:$vsdir/User/mcp.json"; fi

    local cddir="$HOME/.config/Claude"
    [ "$(uname -s)" = "Darwin" ] && cddir="$HOME/Library/Application Support/Claude"
    if [ "$ALL_HARNESS" = "1" ] || [ -d "$cddir" ]; then items="$items claude:$cddir/claude_desktop_config.json"; fi
  else
    # repo-local wiring: project configs only (Claude Code picks up
    # the project servers in .mcp.json; OpenCode/Cursor/Gemini/Gemini CLI
    # each have their own project-level file)
    items="$items claude:$REPO_ROOT/.mcp.json"
    items="$items cursor:$REPO_ROOT/.cursor/mcp.json"
    items="$items opencode:$REPO_ROOT/opencode.json"
    items="$items gemini:$REPO_ROOT/.gemini/settings.json"
    items="$items vscode:$REPO_ROOT/.vscode/mcp.json"
  fi

  local item mode file hits=0
  for item in $items; do
    mode="${item%%:*}"
    file="${item#*:}"
    if [ "$mode" = "codex" ]; then
      if register_codex_toml "$file" "$( [ "$action" = "remove" ] && echo 1 || echo 0 )"; then hits=$((hits+1)); fi
    else
      if merge_mcp "$mode" "$file" "$cmd" "$action"; then hits=$((hits+1)); fi
    fi
  done

  if [ "$action" = "add" ] && [ "$hits" = "0" ] && [ "$SCOPE" = "global" ]; then
    warn "no supported harness found on this machine (OpenCode/Claude/Cursor/Codex/Gemini/Windsurf/VS Code)."
    say "  SMP is still installed — wire it manually or rerun with --all-harnesses."
  fi
}

# --------------------------------------------------------------------- visuals
banner() {
  printf '\n'
  printf '%s\n' "${BOLD}${CYAN}  ┌──────────────────────────────────────────────────┐${RESET}"
  printf '%s\n' "${BOLD}${CYAN}  │${RESET}  ${BOLD}SMP — Structural Memory Protocol${RESET}  ${DIM}installer${RESET}  ${BOLD}${CYAN}│${RESET}"
  printf '%s\n' "${BOLD}${CYAN}  │${RESET}  ${DIM}${REPO_URL}${RESET}  ${BOLD}${CYAN}│${RESET}"
  printf '%s\n' "${BOLD}${CYAN}  └──────────────────────────────────────────────────┘${RESET}"
  printf '\n'
}

print_summary() {
  local skill_note
  local scope_note
  if [ "$SCOPE" = "global" ]; then
    skill_note="~/.agents/skills/smp · ~/.claude/skills/smp · ~/.config/opencode/skills/smp · ~/.codex/skills/smp"
    scope_note="every repo on this machine (user-level harness configs + global skill)"
  else
    skill_note="$REPO_ROOT/.agents/skills/smp · $REPO_ROOT/.claude/skills/smp"
    scope_note="this repo only (project .mcp.json / opencode.json / .cursor / .gemini / .vscode)"
  fi
  if [ "$SKIP_SKILLS" = "1" ]; then skill_note="skipped (--skip-skills)"; fi
  echo
  printf '%s\n' "${BOLD}${GREEN}  ✔ SMP installed successfully${RESET}"
  say ""
  say "${BOLD}wiring scope  ${RESET} ${scope_note}"
  say "${BOLD}binaries      ${RESET} ${BINDIR}/smp       CLI (ingest / serve / mcp / backup / …)"
  say "                ${BINDIR}/smp-mcp     MCP launcher — per-repo graph + auto first ingest"
  say "${BOLD}install tree  ${RESET} ${SMPSYS}   (shared runtime)"
  say "${BOLD}agent skill   ${RESET} ${skill_note}"
  say "${BOLD}graph${RESET}           one .smp/graph.smpg file per repo — created on first use"
  say ""
  say "${BOLD}try it${RESET}"
  if [ "$SCOPE" = "global" ]; then
    say "  1. restart your agent harness (OpenCode / Claude Code / Cursor / Codex / …)"
  else
    say "  1. restart your agent harness from inside $REPO_ROOT"
    say "     (Claude Code will ask once to approve the project server in .mcp.json)"
  fi
  say "  2. ask things like:"
  say "       \"what calls handle_error()?\"      → smp_trace incoming"
  say "       \"what breaks if this changes?\"   → smp_impact"
  say "       \"where is the auth flow?\"        → smp_locate"
  say "  3. manual graph build (optional):  ${BINDIR}/smp ingest <dir>"
  say ""
  say "${BOLD}env toggles${RESET}  SMP_AUTO_INGEST=0 · SMP_GRAPH_PATH=<abs path>"
  say "${BOLD}uninstall${RESET}    curl -fsSL https://raw.githubusercontent.com/${REPO_SLUG}/main/install.sh | bash -s -- --uninstall"
  printf '\n'
}

# ----------------------------------------------------------------------- main
main() {
  banner

  ask_scope
  ok "wiring scope: $SCOPE"
  if [ "$SCOPE" = "local" ]; then
    REPO_ROOT="$(resolve_repo_root)"
    ok "repo root: $REPO_ROOT (wiring only affects this repo)"
    if [ "$REPO_ROOT" = "$HOME" ]; then
      warn "repo root resolved to your home directory — global wiring is the better fit; use --global instead"
    fi
  fi
  set_targets

  if [ "$DO_UNINSTALL" = "1" ]; then
    step "uninstalling SMP ($SCOPE wiring)"
    if [ "$SCOPE" = "global" ]; then
      if [ -x "$BINDIR/smp" ];     then rm -f "$BINDIR/smp";     say "  removed $BINDIR/smp"; fi
      if [ -x "$BINDIR/smp-mcp" ]; then rm -f "$BINDIR/smp-mcp"; say "  removed $BINDIR/smp-mcp"; fi
      if [ "$SKIP_SKILLS" = "0" ]; then uninstall_skill_files; say "  removed global SKILL.md copies"; fi
      step "removing MCP registrations from user-level harness configs"
      register_mcp_all remove
      remove_created_files global
      if [ -d "$SMPSYS" ]; then
        rm -rf "$SMPSYS"
        say "  removed install tree $SMPSYS"
      fi
      ok "SMP uninstalled globally"
    else
      if [ "$SKIP_SKILLS" = "0" ]; then uninstall_skill_files; say "  removed repo SKILL.md copies"; fi
      step "removing MCP registrations from repo configs (only entries pointing at this install)"
      register_mcp_all remove
      remove_created_files local
      say "  runtime at $SMPSYS kept (shared) — to remove it too run with --global --uninstall"
      ok "SMP uninstalled for this repo"
    fi
    return 0
  fi

  command -v curl >/dev/null 2>&1 || die "curl is required (https://curl.se)"
  command -v tar  >/dev/null 2>&1 || die "tar is required"

  mkdir -p "$SMPSYS" || die "cannot create install root $SMPSYS"

  # ---------------------------------------------------------------- python
  step "checking for Python (>= 3.11)"
  local PYBIN
  PYBIN="$(ensure_python)" || die_no_python
  ok "using $("$PYBIN" --version 2>&1 | head -n 1)"

  # ---------------------------------------------------------------- source
  step "getting SMP source"
  local SRC_FETCHED=""
  SRC_FETCHED="$(detect_local_repo || true)"
  if [ -n "$SRC_FETCHED" ]; then
    ok "detected SMP checkout: $SRC_FETCHED (installing from it)"
  else
    SRC_FETCHED="$(fetch_tarball)"
    ok "downloaded: $SRC_FETCHED"
  fi

  # ---------------------------------------------------------------- venv
  step "creating venv at $VENVDIR"
  rm -rf "$VENVDIR" "$SRCDIR" 2>/dev/null || true
  if ! "$PYBIN" -m venv "$VENVDIR" 2>"$SMPSYS/setup-errors.log"; then
    die "venv creation failed (Ubuntu/Debian missing venv module? sudo apt install python3-venv). Log: $SMPSYS/setup-errors.log"
  fi
  ok "venv ready"

  step "installing SMP + all language grammars (one-time download, ~200 MB)"
  local t0=$SECONDS
  "$VENVDIR/bin/pip" install --disable-pip-version-check --quiet --upgrade pip wheel setuptools >/dev/null 2>&1 || true
  if ! "$VENVDIR/bin/pip" install --disable-pip-version-check --quiet "$SRC_FETCHED" 2>"$SMPSYS/pip-errors.log"; then
    if [ "$SRC_FETCHED" != "$SRCDIR" ]; then
      warn "pip install from temp dir failed — retrying after staging into $SRCDIR"
      sync_tree "$SRC_FETCHED" || die "could not stage source"
      if ! "$VENVDIR/bin/pip" install --disable-pip-version-check "$SRCDIR" 2>>"$SMPSYS/pip-errors.log"; then
        die "pip install failed. Full log: $SMPSYS/pip-errors.log"
      fi
    else
      die "pip install failed. Full log: $SMPSYS/pip-errors.log"
    fi
  fi
  say "  took $((SECONDS - t0))s"
  ok "SMP installed into $VENVDIR"

  if [ "$SRC_FETCHED" != "$SRCDIR" ]; then
    sync_tree "$SRC_FETCHED" || warn "source staging failed (install itself is fine)"
    cleanup_tmp
  fi

  # ---------------------------------------------------------------- sanity
  step "verifying imports"
  if ! "$VENVDIR/bin/python" - <<'PYCHECK' 2>"$SMPSYS/pip-errors.log"; then
import smp, msgspec, fastapi, mcp, tree_sitter
import smp.protocol.mcp  # the module smp-mcp actually runs — catches bad MCP SDK pins
import smp.cli
PYCHECK
    printf '%s\n' "  MCP SDK or core import failed — common cause: a dependency released an incompatible major version." \
        "  Last 30 lines of $SMPSYS/pip-errors.log:" >&2
    tail -n 30 "$SMPSYS/pip-errors.log" >&2 || true
    die "sanity check failed — not wiring up. Fix the pin in pyproject.toml, rerun the installer."
  fi
  ok "smp imports cleanly"

  write_launchers
  if [ "$ADD_PATH" = "1" ]; then add_path_rc; fi
  case ":${PATH:-}:" in
    *":${BINDIR}:"*) : ;;
    *) say "  ${DIM}note: $BINDIR is not on PATH yet — rerun with --add-path, or open a new terminal (many distros include ~/.local/bin by default)${RESET}" ;;
  esac

  # --------------------------------------------------------------- skills
  if [ "$SKIP_SKILLS" = "0" ]; then
    [ -f "$SRCDIR/skills/smp/SKILL.md" ] || die "skills/smp/SKILL.md missing from source tree"
    install_skill_files "$SRCDIR/skills/smp/SKILL.md"
  else
    say "  skill installation skipped (--skip-skills)"
  fi

  # --------------------------------------------------- harness MCP configs
  if [ "$SKIP_MCP" = "0" ]; then
    step "wiring smp-mcp into agent harness configs"
    register_mcp_all add
    if [ "$ALL_HARNESS" = "1" ]; then
      say "  (--all-harnesses: wrote entries even for harnesses that were not detected)"
    fi
  else
    say "  MCP registration skipped (--skip-mcp)"
  fi

  # ------------------------------------------------------------------ stamp
  local smp_ver
  smp_ver="$("$VENVDIR/bin/python" -c 'import importlib.metadata as m; print(m.version("smp"))' 2>/dev/null || echo unknown)"
  cat > "$STAMPFILE" <<EOF || warn "could not write stamp file (cosmetic only)"
{
  "version": "$smp_ver",
  "ref": "$REF",
  "installed_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "python": "$("$VENVDIR/bin/python" -V 2>&1)",
  "venv": "$VENVDIR",
  "bin": "$BINDIR",
  "source": "$SRCDIR"
}
EOF
  [ -x "$BINDIR/smp" ] || die "launcher missing after install (permission problem?)"
  "$BINDIR/smp" --help >/dev/null 2>&1 || warn "smp CLI did not respond to --help (check $SMPSYS/pip-errors.log)"

  print_summary
}

main "$@"
