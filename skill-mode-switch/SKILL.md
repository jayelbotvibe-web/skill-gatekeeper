---
name: skill-mode-switch
description: "Auto-switch active Hermes skills by detected mode (research/dev/creative). Verified 92% detection accuracy. Cuts system prompt by 26-37% (83% fewer skills loaded). Empirically verified on Hermes v0.13+."
version: 1.4.0
category: devops
---

# Skill Mode Switch

Automatically trims the Hermes skill catalog based on what you're doing. Instead of loading all 112 skills into every system prompt (~2,900 tokens of noise), the gatekeeper detects your mode from keyword scoring and keeps only the relevant ones.

**Measured impact (research mode):** Skills consume ~41% of system prompt. Gatekeeper cuts skill catalog from 112 → 17 (85% fewer), reducing total system prompt by ~32% (~2,300 tokens/turn saved). Over a 30-turn session: ~69,000 tokens saved.

## Verified Performance

| Metric | Value | Source |
|--------|-------|--------|
| Keyword accuracy | **92%** (45/49) | 50-prompt benchmark, threshold=1 |
| False positives | **0** | Neutral prompts ("hello", "thanks") never trigger a mode |
| `/reload-skills` integration | **Verified** | Hermes v0.13+ — 17 skills visible after reload |
| Filesystem safety | **File-locked + atomic** | `fcntl.flock` + same-device assertion |
| Crash recovery | **Yes** | `in_progress` flag detects partial state, refuses to proceed |
| Data loss risk | **Zero** | No delete operations in codebase; `--reset` always works |
| Functional confidence | **~96%** | See `references/confidence-model.md` |

## How It Works

1. You send a message
2. Agent runs `python3 skill-gatekeeper.py --detect "<your message>"`
3. Keyword scoring assigns points to 8 modes (research, dev, creative, productivity, infra, data, gaming, social)
4. If best score ≥ 1, gatekeeper moves irrelevant `SKILL.md` files to `skills-disabled/`
5. Agent tells you to run `/reload-skills`
6. Next turn: 16-38 skills loaded instead of 111

### Persistent Default Mode

The `--set-default` command persists your preferred mode across sessions. The `--boot` command reapplies it — used in a cron job so gateway restarts don't reset your skills.

```
Gateway restart → Hermes loads 112 → cron --boot (every 30min) → skills re-trimmed
```

**Commands:**
```bash
python3 skill-gatekeeper.py --set-default dev   # Persist "dev" as your default
python3 skill-gatekeeper.py --boot              # Reapply saved default mode
python3 skill-gatekeeper.py --reset             # Temporarily restore all (keeps default)
```

**Cron setup — two approaches:**

*Approach A: System crontab (if available)*
```bash
(crontab -l 2>/dev/null; echo "*/30 * * * * python3 /opt/data/scripts/skill-gatekeeper.py --boot") | crontab -
```

*Approach B: Hermes scheduler (crontab not available on restricted VPS)*
```bash
# 1. Create wrapper script
cat > ~/scripts/gatekeeper-boot.sh << 'EOF'
#!/bin/bash
python3 /opt/data/scripts/skill-gatekeeper.py --boot
EOF
chmod +x ~/scripts/gatekeeper-boot.sh

# 2. Schedule via Hermes cronjob tool — no_agent=true (script-only, zero LLM cost):
#    schedule: */30 * * * *, script: gatekeeper-boot.sh, no_agent: true
#    Name: gatekeeper-auto-boot
#
# The Hermes scheduler runs the script every 30min. Silent on success (empty stdout),
# alerts on failure (non-zero exit). No tokens consumed.
```

The state file at `$HERMES_HOME/.skill-gatekeeper-state.json` (e.g. `/opt/data/.skill-gatekeeper-state.json`) stores both the current `mode` and the persistent `default_mode`. `--reset` restores all skills to disk but sets `mode: "all"` while keeping `default_mode`. Next `--boot` re-trims.

## Modes

| Mode | Skills | Token savings | Example trigger |
|------|--------|--------------|-----------------|
| `research` | 17 | ~32% | "Research latest CVEs" |
| `dev` | 37 | ~26% | "Fix this Python bug" |
| `creative` | 25 | ~30% | "Design a landing page" |
| `productivity` | 26 | ~30% | "Schedule my workout" |
| `podcast` | 14 | ~35% | "Publish episode 10" |
| `data` | 12 | ~35% | "Train this model" |
| `infra` | 18 | ~33% | "Check Docker containers" |
| `gaming` | 5 | ~37% | "Setup Minecraft server" |
| `social` | 6 | ~37% | "Post to Twitter" |
| `all` | 112 | 0% | Default — ambiguous messages |

## Usage
```
python3 skill-gatekeeper.py --detect "Research latest CVEs and threat actors"
# → Detected: research (score 4) → 17 skills active → Run /reload-skills
```

### Explicit mode
```bash
python3 skill-gatekeeper.py dev              # Switch to dev mode (sticky — becomes default)
```

### Persistent default
```bash
python3 skill-gatekeeper.py --set-default dev   # Set default without switching
python3 skill-gatekeeper.py --boot              # Reapply saved default
```

### Check current mode
```bash
python3 skill-gatekeeper.py --list
```

### Reset to all skills (temporarily)
```bash
python3 skill-gatekeeper.py --reset          # Restores all 112, keeps default_mode
```

### Diagnostic log review
```bash
python3 skill-gatekeeper.py --review         # 7-day diagnostic report (default)
python3 skill-gatekeeper.py --review 14      # 14-day window
```

Every state change (BOOT, SWITCH, DETECT, RESET, errors) is logged to `logs/gatekeeper.log` with UTC timestamps. `--review` parses the log and shows:
- Total events by type (boots, switches, resets, no-ops, errors)
- BOOT mode distribution
- Boot gap analysis (>60min gaps flagged)
- Error timeline

Use this to scientifically verify the gatekeeper is working over time — no guessing, no spot checks.

## Agent Workflow

At the START of every new session, the agent MUST:

1. Run detection on the user's first substantive message (skip greetings like "hello", "hi")
2. If mode != "all" and mode changed from current: tell user to run `/reload-skills`
3. Do NOT process the request until `/reload-skills` is executed
4. If mode == "all": proceed normally

## Pitfalls

- **Threshold = 1:** Single keyword hit triggers a switch. Neutral prompts score 0 (zero false positives in 50-prompt benchmark). Ties broken alphabetically.
- **Compound keywords:** Multi-word keywords use inclusive matching — ALL words must appear somewhere, not adjacent. "fix this Python bug" matches "fix bug" because both words are present.
- **Recovery:** Wrong mode? `python3 skill-gatekeeper.py --reset` then retry. Nothing is ever deleted.
- **Agent cannot run /reload-skills:** User-side slash command. Agent must ask explicitly.
- **Running the script:** The gatekeeper lives at `/opt/data/scripts/skill-gatekeeper.py`. If not deployed, run from the skill's `scripts/` directory.
- **Sync all files on code change:** When the gatekeeper source changes (threshold, modes, keywords, skill counts), propagate to ALL supporting files: `architecture.html`, `library-analogy.html`, `README.md`, `ARCHITECTURE.md`, and `skill-mode-switch/SKILL.md`. Stale diagrams with old thresholds or mode counts mislead reviewers.
- **No personal-project modes:** The gatekeeper is a public tool. Modes that encode the author's personal projects (specific podcasts, branded content, side businesses) don't belong — they leak personal context and are irrelevant to other users. Keep modes generic and class-level.
- **State/disk inconsistency after `--reset`:** `--reset` moves all skills back to disk but sets `mode: "all"` in state (preserving `default_mode`). Running `--list` may show "Mode: all" with 112 active even though state still has `default_mode: dev`. This is correct — `--boot` re-applies the default. Do NOT manually delete the state file unless you want to lose the persistent default.
- **Hermes loads 112 on gateway restart:** Even with `--set-default dev` + cron `--boot`, a gateway restart loads all 112 skills until the next cron tick (max 30min). The agent should check current skills at session start; if count > expected, suggest `/reload-skills` after confirming the cron has run.

## Known Limitations

These are acknowledged trade-offs, not bugs:

- **Cross-mode friction:** Switching modes mid-session requires `/reload-skills` round-trip. Agent uses signal-based approach (detects need, asks user). ~80% of sessions stay in one mode.
- **Concurrent sessions:** File-locked but stale reads possible if Session A switches during Session B's turn.
- **Filesystem coupling:** Depends on Hermes scanning directory for `SKILL.md` files. Not a stable API.
- **Tie-breaking:** When two modes score equally (e.g., dev:1 + productivity:1), `max()` picks alphabetically. Future: weight by usage frequency.

## Reference Files

- `references/confidence-model.md` — Mathematical confidence breakdown (96% functional)
- `references/accuracy-test-results.md` — 50-prompt benchmark with per-mode scores
- `references/token-savings.md` — Methodology and per-mode savings
- `references/self-critique-2026-05.md` — Post-build devil's advocate: 16 issues found and resolved
- `scripts/skill-gatekeeper.py` — The gatekeeper script (~600 lines, Python stdlib only)
