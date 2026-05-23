#!/usr/bin/env python3
"""
Skill Gatekeeper — Mode-based skill filter for Hermes Agent.

Manages which skills are active by moving SKILL.md files between
the active skills directory and a disabled archive. Hermes picks up
changes on /reload-skills.

Usage:
    python3 skill-gatekeeper.py research           # Explicit mode
    python3 skill-gatekeeper.py --detect "text"    # Auto-detect from prompt
    python3 skill-gatekeeper.py --list             # Show current mode + active skills
    python3 skill-gatekeeper.py --reset            # Restore ALL skills temporarily
    python3 skill-gatekeeper.py --set-default dev  # Set persistent default mode
    python3 skill-gatekeeper.py --boot             # Reapply saved default mode
    python3 skill-gatekeeper.py --review           # Diagnostic log review
"""

import os
import sys
import json
import shutil
import re
import fcntl
from pathlib import Path
from collections import defaultdict

# Paths — configurable via HERMES_HOME env var, falls back to /opt/data
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
SKILLS_DIR = _HERMES_HOME / "skills"
DISABLED_DIR = _HERMES_HOME / "skills-disabled"
STATE_FILE = _HERMES_HOME / ".skill-gatekeeper-state.json"
LOCK_FILE = _HERMES_HOME / ".skill-gatekeeper.lock"
LOG_FILE = _HERMES_HOME / "logs" / "gatekeeper.log"

# ─── Logging ─────────────────────────────────────────────────────────

from datetime import datetime, timezone

def _log(event: str, details: str = "") -> None:
    """Append a timestamped entry to the diagnostic log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {event}"
    if details:
        line += f" | {details}"
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ─── Mode → Skill Mappings ───────────────────────────────────────────

# Format: {mode: [list of category/skill-name]}
# Skills under "always" are included in EVERY mode.
# Skills can appear in multiple modes.

MODE_SKILLS: dict[str, list[str]] = {
    "always": [
        # Self-referential — agent needs to understand itself
        "autonomous-ai-agents/hermes-agent",
        # Gatekeeper's own skill — agent must know how to use the gatekeeper
        "devops/skill-mode-switch",
    ],

    "research": [
        # Core research
        "research/arxiv",
        "research/blogwatcher",
        "research/llm-wiki",
        "research/polymarket",
        "research/threat-intelligence",
        "research/research-paper-writing",
        # YouTube intelligence
        "media/youtube-content",
        "media/youtube-channel-audit",
        # Red team / security
        "red-teaming/godmode",
        # ML eval for paper analysis
        "mlops/evaluation/lm-evaluation-harness",
        "mlops/evaluation/weights-and-biases",
        "mlops/research/dspy",
        # Media search
        "media/gif-search",
        # Utilities
        "productivity/maps",
        "browser/remote-browser-cdp",
    ],

    "podcast": [
        "media/podcast-production",
        "media/zeroday-production",
        "media/zeroday-blog-publishing",
        "note-taking/notebooklm-briefing",
        "media/youtube-content",
        "media/youtube-channel-audit",
        "productivity/audio-learning-drills",
        "social-media/content-promotion-playbook",
        "social-media/xurl",
        "thumbnail-generation",
        "media/gif-search",
        "browser/remote-browser-cdp",
    ],

    "dev": [
        # Coding agents
        "autonomous-ai-agents/claude-code",
        "autonomous-ai-agents/codex",
        "autonomous-ai-agents/opencode",
        # GitHub workflow
        "github/github-auth",
        "github/github-code-review",
        "github/github-issues",
        "github/github-pr-workflow",
        "github/github-repo-management",
        "github/codebase-inspection",
        # Development methodology
        "software-development/plan",
        "software-development/spike",
        "software-development/writing-plans",
        "software-development/subagent-driven-development",
        "software-development/systematic-debugging",
        "software-development/test-driven-development",
        "software-development/requesting-code-review",
        # Debugging
        "software-development/debugging-hermes-tui-commands",
        "software-development/hermes-agent-skill-authoring",
        "software-development/node-inspect-debugger",
        "software-development/python-debugpy",
        # Infra
        "devops/self-hosted-static-site",
        "devops/zerodaybrief-website",
        "devops/friend-hermes-admin",
        "devops/friend-proxy-setup",
        "devops/environment-troubleshooting",
        "devops/skill-security-scanner",
        "devops/vps-infrastructure",
        "devops/vps-migration",
        "devops/webhook-subscriptions",
        "hostinger-hermes-multi-instance",
        "mcp/native-mcp",
        "devops/model-auto-switch",
        "devops/kanban-orchestrator",
        "devops/kanban-worker",
        "browser/remote-browser-cdp",
    ],

    "creative": [
        "creative/architecture-diagram",
        "creative/ascii-art",
        "creative/ascii-video",
        "creative/baoyu-comic",
        "creative/baoyu-infographic",
        "creative/claude-design",
        "creative/comfyui",
        "creative/creative-ideation",
        "creative/design-md",
        "creative/excalidraw",
        "creative/humanizer",
        "creative/manim-video",
        "creative/p5js",
        "creative/pixel-art",
        "creative/popular-web-designs",
        "creative/pretext",
        "creative/sketch",
        "creative/songwriting-and-ai-music",
        "creative/touchdesigner-mcp",
        "media/heartmula",
        "media/gif-search",
        "thumbnail-generation",
        "browser/remote-browser-cdp",
    ],

    "data": [
        "data-science/jupyter-live-kernel",
        "mlops/evaluation/lm-evaluation-harness",
        "mlops/evaluation/weights-and-biases",
        "mlops/huggingface-hub",
        "mlops/inference/llama-cpp",
        "mlops/inference/obliteratus",
        "mlops/inference/vllm",
        "mlops/models/audiocraft",
        "mlops/models/segment-anything",
        "mlops/research/dspy",
    ],

    "productivity": [
        "productivity/airtable",
        "productivity/audio-learning-drills",
        "productivity/file-housekeeping",
        "productivity/google-workspace",
        "productivity/linear",
        "productivity/maps",
        "productivity/nano-pdf",
        "productivity/notion",
        "productivity/ocr-and-documents",
        "productivity/personal-coaching",
        "productivity/powerpoint",
        "productivity/teams-meeting-pipeline",
        "apple/apple-notes",
        "apple/apple-reminders",
        "apple/findmy",
        "apple/imessage",
        "email/himalaya",
        "note-taking/obsidian",
        "media/spotify",
        "social-media/xurl",
        "social-media/content-promotion-playbook",
        "browser/remote-browser-cdp",
    ],

    "infra": [
        "devops/friend-hermes-admin",
        "devops/friend-proxy-setup",
        "devops/environment-troubleshooting",
        "devops/vps-infrastructure",
        "devops/vps-migration",
        "devops/skill-security-scanner",
        "devops/kanban-orchestrator",
        "devops/kanban-worker",
        "devops/model-auto-switch",
        "devops/webhook-subscriptions",
        "devops/self-hosted-static-site",
        "devops/zerodaybrief-website",
        "hostinger-hermes-multi-instance",
        "mcp/native-mcp",
        "browser/remote-browser-cdp",
    ],

    "gaming": [
        "gaming/minecraft-modpack-server",
        "gaming/pokemon-player",
    ],

    "social": [
        "social-media/xurl",
        "social-media/content-promotion-playbook",
        "media/spotify",
        "media/gif-search",
    ],
}

# ─── Mode Detection Keywords ──────────────────────────────────────────

# Each keyword adds weight to a mode. Higher total = detected mode.
# Minimum score of 2 required to auto-switch (prevents false positives).
# Keywords are matched case-insensitive.

MODE_KEYWORDS: dict[str, list[str]] = {
    "research": [
        "research", "arxiv", "cve", "threat intel", "vulnerability",
        "exploit", "zero-day", "zero day", "malware", "ransomware",
        "breach", "campaign", "actor", "apt", "attack", "advisory",
        "polymarket", "market odds", "prediction market",
        "paper", "literature review", "survey", "state of the art",
        "blog", "rss", "feed", "news", "what is", "explain",
        "summarize", "wiki", "knowledge base", "learn about",
        "youtube channel", "transcript", "video summary",
        "find me", "look up", "search for", "any news",
    ],
    "podcast": [
        "podcast", "episode", "zeroday brief", "zeroday_brief",
        "briefing", "show notes", "recording", "notebooklm",
        "audio overview", "production", "publish episode",
        "script", "cold open", "stretch cue", "analogy",
        "ep0", "ep1", "ep2", "ep3", "ep4", "ep5",
    ],
    "dev": [
        "code", "debug", "test", "build", "deploy", "commit",
        "pull request", "github", "git", "fix bug", "refactor",
        "implement", "develop", "program", "review code",
        "merge", "branch", "push", "repo",
        "python", "node", "javascript", "typescript", "rust", "go",
        "api", "endpoint", "route", "function", "class", "module",
        "docker", "container", "config",
        "subagent", "plan", "tdd", "write code", "feature",
        "ci/cd", "pipeline", "lint", "format",
        "error", "traceback", "crash", "broken", "doesn't work",
        "investigate", "root cause", "what happened",
        "setup", "install", "configure", "dependencies",
        "server", "database", "sql", "query", "migration",
    ],
    "creative": [
        "design", "draw", "create image", "generate image",
        "art", "ascii", "video", "music", "song", "diagram",
        "animation", "sketch", "pixel art", "comfyui",
        "stable diffusion", "dalle", "poster", "logo",
        "banner", "infographic", "comic", "visual",
        "render", "svg", "html design", "landing page",
        "prototype", "mockup", "wireframe", "ui design",
        "excalidraw", "hand-drawn", "manim", "3blue1brown",
        "p5js", "generative art", "shader",
        "make me a", "create a website", "design a page",
    ],
    "data": [
        "csv", "jupyter", "notebook", "plot", "chart",
        "statistics", "ml model", "train", "fine-tune",
        "dataset", "pandas", "numpy", "visualization",
        "analysis", "metrics", "evaluation", "benchmark",
        "huggingface", "wandb", "weights and biases",
        "llama.cpp", "vllm", "gguf", "quantize",
        "embeddings", "tokenizer", "segmentation",
        "musicgen", "audiocraft", "text to music",
    ],
    "productivity": [
        "calendar", "email", "schedule", "meeting",
        "document", "slide", "presentation", "spreadsheet",
        "note", "notion", "task", "todo", "reminder",
        "google docs", "google sheets", "gmail",
        "powerpoint", "airtable", "linear issue",
        "ocr", "pdf", "scan", "extract text",
        "workout", "nutrition", "coaching", "fitness",
        "maps", "directions", "geocode", "route",
        "apple note", "reminder", "find my", "imessage",
        "obsidian", "himalaya", "spotify",
    ],
    "infra": [
        "vps", "server", "docker", "container", "proxy",
        "iptables", "network", "port", "tunnel",
        "hostinger", "gateway", "mcp server",
        "friend hermes", "hermes-friend", "multi-instance",
        "kanban", "webhook", "cron job",
        "security scan", "audit", "harden",
        "migrate", "migration", "backup server",
    ],
}

# Minimum keyword score to auto-switch.
# Set to 1 — conservative enough to avoid false positives on neutral
# prompts (tested on 50 prompts: 92% accuracy, 0 false positives).
# Tie-breaking: when multiple modes score equally, max() picks the
# first alphabetically. This means "dev" beats "research" on ties.
# Future: weight modes by historical usage frequency.
MIN_AUTO_SCORE = 1


# ─── Core Logic ─────────────────────────────────────────────────────

def _normalize_skill_path(name: str) -> str:
    """Normalize a skill identifier like 'category/subcat/name' or 'category/name'."""
    return name.strip("/")


def get_active_skills() -> set[str]:
    """Return set of currently active skill identifiers."""
    active = set()
    if not SKILLS_DIR.exists():
        return active
    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        rel = skill_md.relative_to(SKILLS_DIR)
        # e.g., "research/arxiv/SKILL.md" → "research/arxiv"
        parts = rel.parts
        if len(parts) >= 2:
            active.add("/".join(parts[:-1]))
    return active


def get_all_skills() -> set[str]:
    """Return set of ALL skill identifiers (active + disabled)."""
    all_skills = get_active_skills()
    if DISABLED_DIR.exists():
        for skill_md in DISABLED_DIR.rglob("SKILL.md"):
            rel = skill_md.relative_to(DISABLED_DIR)
            parts = rel.parts
            if len(parts) >= 2:
                all_skills.add("/".join(parts[:-1]))
    return all_skills


def get_skills_for_mode(mode: str) -> set[str]:
    """Get the full set of skills that should be active for a mode."""
    if mode == "all":
        return get_all_skills()

    skills = set(MODE_SKILLS.get("always", []))

    if mode in MODE_SKILLS:
        skills.update(MODE_SKILLS[mode])

    # Validate that all referenced skills actually exist
    all_skills = get_all_skills()
    valid = set()
    missing = set()
    for s in skills:
        if s in all_skills:
            valid.add(s)
        else:
            # Try fuzzy match
            found = False
            for as_name in all_skills:
                if as_name.endswith("/" + s.split("/")[-1]):
                    valid.add(as_name)
                    found = True
                    break
            if not found:
                missing.add(s)

    if missing:
        print(f"⚠ Warning: {len(missing)} skill(s) not found: {', '.join(sorted(missing))[:200]}",
              file=sys.stderr)

    return valid


def _detect_partial_state() -> bool:
    """Check if a previous switch crashed mid-operation, leaving partial state.
    
    Uses an in-progress marker in the state file. Before any switch begins,
    we set 'in_progress': true. After completion, we clear it. If we find
    'in_progress': true on startup, the previous run crashed.
    """
    try:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except (json.JSONDecodeError, IOError):
        return False
    return state.get("in_progress", False)


def switch_mode(mode: str, dry_run: bool = False) -> dict:
    """
    Switch to the specified mode. Moves SKILL.md files between
    SKILLS_DIR and DISABLED_DIR to match the mode's skill set.

    Uses file locking to prevent concurrent switches from corrupting state.
    Detects and refuses to proceed if a previous switch crashed mid-operation.
    Returns stats dict: {enabled, disabled, mode, dry_run}
    """
    # Check for crash/partial state before proceeding
    if _detect_partial_state():
        print("⚠ Detected partial state from a previous crash.", file=sys.stderr)
        print("  Run: python3 skill-gatekeeper.py --reset", file=sys.stderr)
        print("  Then try switching modes again.", file=sys.stderr)
        return {"mode": mode, "enabled": 0, "disabled": 0,
                "active_total": len(get_active_skills()), "dry_run": dry_run,
                "error": "partial_state_detected"}

    desired = get_skills_for_mode(mode)
    current = get_active_skills()

    to_enable = desired - current
    to_disable = current - desired

    if not dry_run and (to_enable or to_disable):
        # Verify same filesystem — shutil.move() is atomic only on same-FS rename
        if DISABLED_DIR.exists():
            try:
                if SKILLS_DIR.stat().st_dev != DISABLED_DIR.stat().st_dev:
                    print("⚠ Skills dir and disabled dir are on different filesystems.",
                          file=sys.stderr)
                    print(f"  skills: device {SKILLS_DIR.stat().st_dev}", file=sys.stderr)
                    print(f"  disabled: device {DISABLED_DIR.stat().st_dev}", file=sys.stderr)
                    print("  Cross-filesystem moves are non-atomic. Aborting.", file=sys.stderr)
                    return {"mode": mode, "enabled": 0, "disabled": 0,
                            "active_total": len(current), "dry_run": dry_run,
                            "error": "cross_filesystem"}
            except OSError:
                pass  # stat failed; proceed and let shutil.move() catch the error
        DISABLED_DIR.mkdir(parents=True, exist_ok=True)

        # Mark operation as in-progress (crash detection)
        _save_state(mode, set(), in_progress=True)

        # Acquire file lock to prevent concurrent switches
        with open(LOCK_FILE, 'w') as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            # Disable: move from skills/ → skills-disabled/
            for skill_name in to_disable:
                src = SKILLS_DIR / skill_name
                dst = DISABLED_DIR / skill_name
                if src.exists() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))

            # Enable: move from skills-disabled/ → skills/
            for skill_name in to_enable:
                src = DISABLED_DIR / skill_name
                dst = SKILLS_DIR / skill_name
                if src.exists():
                    if dst.exists():
                        shutil.rmtree(str(dst))
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))

            fcntl.flock(lock_fd, fcntl.LOCK_UN)

    # Save state (with mode as new default)
    _save_state(mode, desired, default_mode=mode)

    return {
        "mode": mode,
        "enabled": len(to_enable),
        "disabled": len(to_disable),
        "active_total": len(desired),
        "dry_run": dry_run,
    }


def detect_mode(text: str) -> tuple[str, dict[str, int]]:
    """
    Auto-detect the best mode from text.
    Returns (mode_name, scores_dict).
    Defaults to 'all' if no mode scores above threshold.
    """
    text_lower = text.lower()
    scores: dict[str, int] = defaultdict(int)

    for mode, keywords in MODE_KEYWORDS.items():
        for kw in keywords:
            words = kw.split()
            if len(words) == 1:
                # Single word: substring or word-boundary match
                if kw in text_lower:
                    scores[mode] += 1
                elif len(kw) <= 8 and re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                    scores[mode] += 1
            else:
                # Multi-word: ALL words must be present anywhere in text
                if all(w in text_lower for w in words):
                    scores[mode] += 1

    if not scores:
        return "all", dict(scores)

    best_mode = max(scores, key=scores.get)
    best_score = scores[best_mode]

    if best_score < MIN_AUTO_SCORE:
        return "all", dict(scores)

    return best_mode, dict(scores)


def _save_state(mode: str, skills: set[str], in_progress: bool = False, default_mode: str = None) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "mode": mode,
        "active_skills": sorted(skills) if skills else [],
        "active_count": len(skills),
        "in_progress": in_progress,
    }
    # Carry forward existing default_mode if not explicitly set
    old = {}
    if STATE_FILE.exists() and default_mode is None:
        try:
            old = json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    data["default_mode"] = default_mode or old.get("default_mode", "all")
    STATE_FILE.write_text(json.dumps(data, indent=2))


def get_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"mode": "all", "active_count": len(get_active_skills())}


def reset_all() -> dict:
    """Restore ALL skills to the active directory. Preserves default_mode."""
    if DISABLED_DIR.exists():
        for skill_md in DISABLED_DIR.rglob("SKILL.md"):
            rel = skill_md.relative_to(DISABLED_DIR)
            parts = rel.parts
            if len(parts) >= 2:
                skill_dir = "/".join(parts[:-1])
                src = DISABLED_DIR / skill_dir
                dst = SKILLS_DIR / skill_dir
                if src.exists():
                    if dst.exists():
                        shutil.rmtree(str(dst))
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
        for d in sorted(DISABLED_DIR.rglob("*"), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        if DISABLED_DIR.exists() and not any(DISABLED_DIR.iterdir()):
            DISABLED_DIR.rmdir()

    all_skills = get_active_skills()
    _save_state("all", all_skills)
    return {"mode": "all", "active_count": len(all_skills)}


# ─── Review ──────────────────────────────────────────────────────────

def review_log(days: int = 7) -> str:
    """Parse the log and return a diagnostic report for the last N days."""
    if not LOG_FILE.exists():
        return "No log file found — gatekeeper has not logged any events yet."

    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    events = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ts_str = line[1:21]  # [YYYY-MM-DDTHH:MM:SSZ]
                ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
                if ts < cutoff:
                    continue
                event = line[23:].split(" | ", 1)
                events.append({"ts": ts, "event": event[0], "details": event[1] if len(event) > 1 else ""})
            except (ValueError, IndexError):
                continue

    if not events:
        return f"No events in the last {days} days."

    boots = [e for e in events if e["event"] == "BOOT"]
    switches = [e for e in events if e["event"] in ("SWITCH", "DETECT_SWITCH")]
    errors = [e for e in events if "ERROR" in e["event"]]
    resets = [e for e in events if e["event"] == "RESET"]
    noops = [e for e in events if "NOOP" in e["event"]]

    # Mode distribution from boots
    mode_counts = {}
    for b in boots:
        detail = b["details"]
        for part in detail.split():
            if part.startswith("mode="):
                mode_counts[part[5:]] = mode_counts.get(part[5:], 0) + 1

    # Boot gap analysis (alert if gap > 60 min)
    boot_gaps = []
    sorted_boots = sorted(boots, key=lambda x: x["ts"])
    for i in range(1, len(sorted_boots)):
        gap_min = (sorted_boots[i]["ts"] - sorted_boots[i-1]["ts"]) / 60
        if gap_min > 60:
            boot_gaps.append(gap_min)

    report = []
    report.append(f"╔══════════════════════════════════════════╗")
    report.append(f"║  Gatekeeper Diagnostic Report ({days}d)   ║")
    report.append(f"╚══════════════════════════════════════════╝")
    report.append("")
    report.append(f"Total events:      {len(events)}")
    report.append(f"  BOOT cycles:     {len(boots)}")
    report.append(f"  Mode switches:   {len(switches)}")
    report.append(f"  Resets:          {len(resets)}")
    report.append(f"  No-op detects:   {len(noops)}")
    report.append(f"  Errors:          {len(errors)}")
    report.append("")
    if mode_counts:
        report.append("BOOT mode distribution:")
        for mode, count in sorted(mode_counts.items(), key=lambda x: -x[1]):
            report.append(f"  {mode}: {count}")
    if boot_gaps:
        report.append("")
        report.append(f"⚠ Boot gaps > 60min: {len(boot_gaps)}")
        for g in boot_gaps:
            report.append(f"  {g:.0f}min gap — cron may have missed a cycle")
    if errors:
        report.append("")
        report.append("⚠ Errors:")
        for e in errors:
            report.append(f"  [{datetime.fromtimestamp(e['ts'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}Z] {e['event']}: {e['details']}")
    if not boot_gaps and not errors:
        report.append("✓ No anomalies detected. Gatekeeper is healthy.")
    report.append("")
    report.append(f"Log file: {LOG_FILE}")
    report.append(f"Review period: last {days} days")

    return "\n".join(report)


# ─── CLI ─────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: skill-gatekeeper.py <mode|--detect|--list|--reset>")
        print(f"Modes: all, {', '.join(MODE_SKILLS.keys())}")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--list":
        state = get_state()
        active = get_active_skills()
        print(f"Mode: {state.get('mode', 'unknown')}")
        print(f"Active skills: {len(active)}")
        for s in sorted(active):
            print(f"  {s}")
        return

    if arg == "--review":
        days = 7
        if len(sys.argv) > 2:
            try:
                days = int(sys.argv[2])
            except ValueError:
                print(f"Invalid days: {sys.argv[2]}")
                sys.exit(1)
        print(review_log(days))
        return

    if arg == "--reset":
        result = reset_all()
        _log("RESET", f"restored all {result['active_count']} skills")
        print(f"✓ Reset to all mode — {result['active_count']} skills active")
        print("Run /reload-skills in Hermes to pick up changes.")
        return

    if arg == "--boot":
        state = get_state()
        default = state.get("default_mode", "all")
        print(f"Default mode: {default}")
        if default == "all":
            _log("BOOT", "no default mode set — skipped")
            print("No default mode set — all skills active.")
            return
        result = switch_mode(default)
        if result.get("error"):
            _log("BOOT_ERROR", f"mode={default} error={result.get('error')}")
            return
        _log("BOOT", f"mode={default} active={result['active_total']} "
             f"enabled={result['enabled']} disabled={result['disabled']}")
        print(f"✓ Booted to {default} — {result['active_total']} active "
              f"({result['enabled']} enabled, {result['disabled']} disabled)")
        return

    if arg == "--set-default":
        if len(sys.argv) < 3:
            print(f"Usage: skill-gatekeeper.py --set-default <mode>")
            print(f"Modes: all, {', '.join(MODE_SKILLS.keys())}")
            sys.exit(1)
        mode = sys.argv[2]
        if mode not in MODE_SKILLS and mode != "all":
            print(f"Unknown mode: {mode}")
            sys.exit(1)
        old = get_state()
        current_skills = get_active_skills() if old.get("mode") == "all" else set()
        _save_state(old.get("mode", "all"), current_skills, default_mode=mode)
        _log("SET_DEFAULT", f"mode={mode}")
        print(f"✓ Default mode set to {mode} (will auto-apply on --boot)")
        return

    if arg == "--detect":
        if len(sys.argv) < 3:
            text = sys.stdin.read()
        else:
            text = " ".join(sys.argv[2:])
        mode, scores = detect_mode(text)
        print(f"Detected: {mode}")
        print(f"Scores: {dict(scores)}")
        if mode != "all":
            result = switch_mode(mode)
            if result.get("error"):
                _log("DETECT_ERROR", f"detected={mode} error={result.get('error')}")
                return  # Error already printed by switch_mode
            _log("DETECT_SWITCH", f"detected={mode} scores={dict(scores)} "
                 f"active={result['active_total']} enabled={result['enabled']} "
                 f"disabled={result['disabled']}")
            print(f"✓ Switched to {mode} — {result['active_total']} active "
                  f"({result['enabled']} enabled, {result['disabled']} disabled)")
            print("Run /reload-skills in Hermes to pick up changes.")
        else:
            _log("DETECT_NOOP", f"scores={dict(scores)}")
            print("No strong mode detected — keeping all skills active.")
        return

    # Explicit mode
    mode = arg
    if mode not in MODE_SKILLS and mode != "all":
        print(f"Unknown mode: {mode}")
        print(f"Available: all, {', '.join(MODE_SKILLS.keys())}")
        sys.exit(1)

    result = switch_mode(mode)
    if not result.get("error"):
        _log("SWITCH", f"mode={mode} active={result['active_total']} "
             f"enabled={result['enabled']} disabled={result['disabled']}")
        print(f"✓ Switched to {mode} — {result['active_total']} skills active "
              f"({result['enabled']} enabled, {result['disabled']} disabled)")
        print("Run /reload-skills in Hermes to pick up changes.")


if __name__ == "__main__":
    main()
