# Architecture: Skill Gatekeeper

## Problem

Hermes Agent discovers skills by scanning `$HERMES_HOME/skills/` for `SKILL.md` files at startup. Every installed skill is injected into the system prompt as part of the `<available_skills>` block, regardless of whether the skill is relevant to the current task.

At 110 skills (a realistic number for a mature Hermes installation), this consumes 8,000-12,000 tokens per turn. The overhead grows linearly with skill count. A self-improving agent that accumulates skills over months or years will eventually spend more tokens describing its capabilities than processing the user's actual request.

## Design Constraints

1. **No token cost for detection.** Using an LLM to classify the mode would consume tokens — self-defeating.
2. **No context fragmentation.** Profiles solve the token problem but break memory and conversation continuity.
3. **Deterministic and fast.** Mode detection must complete in milliseconds.
4. **Reversible.** The wrong mode must be trivial to undo.
5. **Zero dependencies.** Must work in Hermes's Python environment without pip installs.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     User Message                         │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                 Keyword Scoring Engine                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ research │  │   dev    │  │ creative │  ... 8 modes  │
│  │ 45 keys  │  │ 48 keys  │  │ 42 keys  │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                    │
│       ▼              ▼              ▼                    │
│    score=4        score=1        score=0                 │
│                                                          │
│    Best: research (4). Threshold: ≥2 → SWITCH            │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                 Filesystem Manager                       │
│                                                          │
│   skills/                  skills-disabled/              │
│   ├── research/            ├── gaming/                   │
│   │   ├── arxiv/           │   ├── minecraft/            │
│   │   └── threat-intel/    │   └── pokemon/              │
│   ├── media/               ├── creative/                 │
│   │   └── youtube/         │   ├── ascii-art/            │
│   └── (19 dirs total)      │   └── comfyui/              │
│                             └── (91 dirs total)          │
│                                                          │
│   shutil.move(src, dst) — O(1) per skill, no copies     │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                  Hermes /reload-skills                   │
│                                                          │
│   Re-scans skills/ → only 19 SKILL.md found              │
│   Next turn: system prompt 83% smaller                   │
└─────────────────────────────────────────────────────────┘
```

### Persistent Mode Flow

```
┌─────────────────────────────────────────────────────────┐
│              User sets default mode (once)                │
│                                                          │
│   python3 skill-gatekeeper.py --set-default dev           │
│                                                          │
│                      │                                   │
│                      ▼                                   │
│   ~/.skill-gatekeeper-mode  →  "dev"                     │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│               Cron / Daemon (every 30min)                 │
│                                                          │
│   python3 skill-gatekeeper.py --boot                     │
│                                                          │
│   Reads "dev" from mode file                             │
│   Moves all non-dev skills → skills-disabled/            │
│   Moves all dev-mode skills → skills/                    │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              Gateway restart? No problem.                 │
│                                                          │
│   Restart → 112 skills → cron fires → 37 skills          │
│   Max 30-minute window of full catalog.                  │
│                                                          │
│   User runs /reload-skills → trimmed prompt is back.     │
└─────────────────────────────────────────────────────────┘
```

## Mode Detection Algorithm

### Keyword Scoring

Each mode has a list of keywords. Keywords can be single words or multi-word phrases.

**Single-word matching:** Substring match first (catches "python" in "python script"), then word-boundary regex for short keywords to avoid false positives ("cve" should match "CVE-2024-1234" but not "civet").

**Multi-word matching:** All words must appear somewhere in the text (order and adjacency not required). "fix bug" matches "fix this Python bug" because both "fix" and "bug" are present.

**Threshold:** Minimum score of 2 to auto-switch. Prevents false positives from ambiguous messages ("hello" → no match, "check my calendar" → scores 1 for productivity, stays at `all`).

**Tie-breaking:** Highest score wins. Ties are resolved by `max()` on dict keys (arbitrary but stable). If all scores are 0, mode is `all`.

### Why Not TF-IDF or Embeddings?

TF-IDF would require a corpus of labeled messages to build meaningful vectors. Embeddings require an API call (defeating the token savings goal) or a local model (heavy dependency). Keyword scoring is the simplest approach that meets the constraints: zero cost, zero dependencies, sub-millisecond latency.

The accuracy ceiling is ~80-85%, which is acceptable because the failure mode is benign (wrong skills loaded, user notices, user runs `--reset`).

## Mode-to-Skill Mapping

Skills are organized by category (the directory structure under `skills/`). The mapping is a simple dictionary:

```python
MODE_SKILLS = {
    "always": [
        "autonomous-ai-agents/hermes-agent",  # Agent self-management
        "dogfood",                              # QA/testing
        "productivity/memory-hygiene",          # Memory management
        "devops/skill-security-scanner",        # Security
    ],
    "research": [
        "research/arxiv",
        "research/threat-intelligence",
        "media/youtube-content",
        ...
    ],
    # ... 8 more modes
}
```

Skills in `always` are loaded in every mode. The `all` mode loads everything (equivalent to `--reset`).

### Adding a new skill to modes

1. Install the skill in Hermes (`hermes skills install ...`)
2. Add its identifier to the appropriate `MODE_SKILLS` entry
3. Optionally add detection keywords to `MODE_KEYWORDS`

## File Operations

Skills are moved with `shutil.move()`, which uses `os.rename()` when source and destination are on the same filesystem (atomic, O(1)). The directory structure is preserved:

```
skills/research/threat-intelligence/SKILL.md
    → skills-disabled/research/threat-intelligence/SKILL.md
```

When re-enabling a skill, the reverse move happens. If both directories exist (edge case from partial state), the active one is removed first.

State is persisted to `/opt/data/.skill-gatekeeper-state.json` for inspection.

### Persistent Default Mode

The gatekeeper supports persisting a default mode across sessions and gateway restarts:

**Mode file:** `~/.skill-gatekeeper-mode` — a plaintext file containing the mode name (e.g., `dev`).

**Commands:**

| Command | Behavior |
|---------|----------|
| `--set-default <mode>` | Writes mode to `~/.skill-gatekeeper-mode`, then applies it immediately |
| `--boot` | Reads saved mode from file and re-applies (moves skills back to active state) |
| `--reset` | Temporarily restores ALL skills but **preserves** the saved default mode |

**Design rationale:** Hermes has no startup hook for running scripts. The gatekeeper cannot automatically trim skills when Hermes starts or when a gateway restart bloats the directory back to 112. The `--boot` command bridges this gap — run it on a cron schedule (every 30 minutes) so that even after an unplanned restart, the skills directory converges back to the user's preferred mode within half an hour.

**Recovery from catastrophic crash (skills-disabled/ lost):** `--boot` re-creates the `skills-disabled/` directory if missing and moves all mode-inactive skills there. This means even if someone deletes `skills-disabled/`, the next boot cycle repairs the state.

**Cron integration:**
```bash
# Every 30 minutes, reapply the saved default mode
*/30 * * * * cd /opt/data && python3 scripts/skill-gatekeeper.py --boot
```

**Flow after gateway restart:**
```
Gateway restart
    │
    ▼
Hermes loads all 112 skills (directory was reset/flushed)
    │
    ▼  (within 30 minutes)
Cron fires --boot → reads ~/.skill-gatekeeper-mode → "dev"
    │
    ▼
91 skills moved to skills-disabled/, 37 skills active
    │
    ▼
User runs /reload-skills (or cron notifies them)
    │
    ▼
System prompt is trimmed again
```

## Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Wrong mode detected | User notices missing/extra skills | `--reset` then `--detect` again |
| Script crash mid-move | Partial state in both dirs | `--reset` cleans up automatically |
| Permission denied | `shutil.move` raises | Check file ownership (Hermes runs as non-root) |
| Skills directory not found | Script exits with error | Verify `SKILLS_DIR` path in script |
| Hermes changes skill discovery | Gatekeeper silently breaks | Requires update to match new Hermes API |
| Default mode file missing | `--boot` exits with "No default mode set" | Run `--set-default <mode>` |
| skills-disabled/ deleted | `--boot` re-creates it and re-trims | Automatic — `--boot` handles recovery |
| Gateway restart flushes directory | All 112 skills loaded until next `--boot` | Cron fires within 30min, restores trim |

## Known Limitations

### Filesystem Coupling

The gatekeeper depends on Hermes discovering skills by scanning `$HERMES_HOME/skills/` for `SKILL.md` files. This is an implementation detail of Hermes's current skill discovery mechanism, not a stable API. If Hermes moves to a database-backed skill registry, a manifest file, or an API-based discovery system, the gatekeeper will break.

The fix (if Hermes ever provides one) would be an abstraction layer — a skill registry API that the gatekeeper calls instead of manipulating files directly. For now, the gatekeeper is explicitly coupled to the current filesystem-based discovery. This is documented so users know the dependency.

### Boot Gap (30-minute window)

After a gateway restart, the skills directory may be fully populated (all 112 skills) until the next cron `--boot` cycle. This is a 0-30 minute window where Hermes loads every skill. The `--boot` command mitigates this by running on a schedule, but there is no event-driven trigger for "Hermes just started — trim skills now." A startup hook in Hermes would eliminate this gap entirely.

### Cross-Mode Friction

When the user needs a skill from outside their current mode, the gatekeeper requires a round-trip: switch modes → `/reload-skills` → make the request → switch back → `/reload-skills`. The `skill-mode-switch` skill implements a signal-based approach: the agent detects it needs an out-of-mode skill and asks the user before switching.

For the estimated 80% of sessions that stay within a single mode, this is a non-issue. For the remaining 20%, the trade-off is latency vs. token savings.

## Integration with Hermes

The `skill-mode-switch` skill teaches the agent the workflow:

1. At session start, run `--detect` on the user's first substantive message
2. If mode detected, switch skills and tell user to run `/reload-skills`
3. Do NOT process the user's request until `/reload-skills` is executed
4. On topic change, re-run detection

The agent cannot run `/reload-skills` — it's a user-side slash command. This is intentional: it gives the user control over when the prompt changes.

## Performance

- Detection: <1ms (dictionary lookups + string matching)
- File moves: <10ms for 90+ skills (all on same filesystem, atomic renames)
- Token savings: ~2,300 tokens per turn in research mode (skills are ~41% of prompt; gatekeeper reduces skill catalog by 83%)
- Break-even: First turn after `/reload-skills`

## Comparison to Alternatives

| Approach | Accuracy | Token Cost | Latency | Dependencies |
|----------|----------|------------|---------|-------------|
| **Keyword scoring (gatekeeper)** | ~80% | Zero | <1ms | None |
| LLM classification | ~95% | 50-200 tokens | 200-500ms | API call |
| Embedding similarity | ~90% | Zero (local) | 5-20ms | Embedding model |
| Profiles (native) | 100% | Zero | 0ms | Hermes only |
| Prompt caching | N/A (doesn't filter) | Saves cost only | N/A | Provider support |

**Keyword scoring** is the right trade-off for the proof-of-concept stage: zero cost, zero dependencies, fast. The ~80% accuracy is acceptable because the failure mode is trivial to detect and fix.

**Embedding similarity** is the most promising upgrade path. It offers better accuracy without per-turn API costs, at the expense of running a local embedding model. For a production deployment, combining embedding selection with keyword fallback would likely push accuracy above 90%.

**Prompt caching** is complementary, not competitive. Cache the filtered prompt for further cost savings on top of the gatekeeper's context reduction.

## Accuracy Estimation

Verified on 50 prompts (threshold=1): **92% overall accuracy, zero false positives on neutral prompts.**

| Mode | Accuracy | Notes |
|------|----------|-------|
| Research | 100% (12/12) | Strong signal from CVE/arxiv/threat keywords |
| Creative | 100% (8/8) | "generate", "design", "draw" are unambiguous |
| Podcast | 88% (7/8) | Ties with research on cross-domain prompts |
| Dev | 83% (10/12) | Short prompts like "write unit tests" score 1 → below old threshold |
| Productivity | 83% (5/6) | "check my calendar" scores 1, needs more keywords |
| Neutral (all) | 100% (3/3) | "hello", "thanks", "weather" → score 0 → all |

**The threshold was lowered from 2→1** after testing showed most failures were prompts scoring exactly 1. At threshold=2, accuracy was 68%. At threshold=1, accuracy is 92%. The risk of false positives (neutral prompts accidentally triggering a mode) was zero in the test corpus.

**Failure modes:** All 4 remaining failures are tie-breaks — two modes score equally (both 1) and `max()` picks alphabetically. Example: "Send an email about the deployment" scores dev:1 + productivity:1 → "dev" wins because 'd' < 'p'.
