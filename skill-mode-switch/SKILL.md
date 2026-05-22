---
name: skill-mode-switch
description: "Auto-switch active Hermes skills by detected mode (research/dev/creative). Reduces system prompt tokens by 65-85% by disabling irrelevant skills."
version: 1.0.0
category: devops
---

# Skill Mode Switch

Automatically trims the Hermes skill catalog based on what you're doing. Instead of loading all 110 skills into every system prompt (~8,000+ wasted tokens), the gatekeeper detects your mode and keeps only the relevant ones. Token savings: 65-85%.

## How It Works

1. You send a message
2. Agent runs `python3 /opt/data/skills/devops/skill-mode-switch/scripts/skill-gatekeeper.py --detect "<your message>"`
3. Gatekeeper matches keywords to detect mode (research, dev, creative, productivity, infra, data, gaming, social)
4. Irrelevant skills are moved to `/opt/data/skills-disabled/`
5. Agent tells you to run `/reload-skills`
6. Next turn: only 16-38 skills loaded instead of 110

## Modes

| Mode | Skills | Use Case |
|------|--------|----------|
| `research` | 19 | CVEs, threat intel, arxiv, YouTube research, market analysis |
| `gaming` | ~12 | "Host a modded Minecraft server" |
| `creative` | 27 | ASCII art, design, diagrams, images, video, music |
| `dev` | 38 | Coding, debugging, GitHub, PRs, testing, subagents |
| `productivity` | 26 | Calendar, email, docs, notes, coaching, maps |
| `data` | 10 | Jupyter, ML, training, datasets, benchmarks |
| `infra` | 18 | Docker, VPS, proxy, network, multi-instance admin |
| `gaming` | 3 | Minecraft, Pokemon |
| `social` | 4 | X/Twitter, Spotify, content promotion |
| `all` | 110 | Everything (default) |

## Usage

### Auto-detect (preferred)
When the user sends their first message in a session, the agent should:
1. Run detection on the message
2. If a mode is detected (score ≥ 2), switch to it
3. Tell the user to run `/reload-skills`

```
python3 /opt/data/skills/devops/skill-mode-switch/scripts/skill-gatekeeper.py --detect "Research latest CVEs"
# → Detected: research → 19 active (83% reduction)
```

### Explicit mode
```
python3 /opt/data/skills/devops/skill-mode-switch/scripts/skill-gatekeeper.py research
# → Switched to research → 17 active
```

### Check current mode
```
python3 /opt/data/skills/devops/skill-mode-switch/scripts/skill-gatekeeper.py --list
```

### Reset to all skills
```
python3 /opt/data/skills/devops/skill-mode-switch/scripts/skill-gatekeeper.py --reset
```

## Agent Workflow

At the START of every new session (or when the user seems to switch topics), the agent MUST:

```
1. Run detection on the user's first message:
   terminal("python3 /opt/data/skills/devops/skill-mode-switch/scripts/skill-gatekeeper.py --detect \"<user message>\"")
   
2. If mode != "all" and the mode changed from current:
   - Tell user: "Switching to {mode} mode — {N} skills active. Run /reload-skills."
   - Do NOT continue with the request until /reload-skills is run
   
3. If mode == "all":
   - Proceed normally with all skills
```

**IMPORTANT:** Do NOT run the switch if the current mode already matches. Check with `--list` first if uncertain.

**IMPORTANT:** After switching modes, the user MUST run `/reload-skills` in their Hermes chat. The agent cannot do this for them. The skills change takes effect on the NEXT turn after `/reload-skills`.

## Pitfalls

- **Detection threshold:** Modes require a minimum score of 2 to auto-switch. This prevents false positives on ambiguous messages like "hello" or "thanks".
- **Topic changes mid-session:** If the user changes topic, re-run detection. If the mode changes, switch and ask for `/reload-skills`.
- **Skills are file-based:** The gatekeeper physically moves SKILL.md files between `/opt/data/skills/` and `/opt/data/skills-disabled/`. This is safe — no data is deleted.
- **Recovery:** If the wrong mode was selected, run `--reset` to restore all skills, then `--detect` again.
- **The agent cannot run `/reload-skills`:** This is a user-side slash command. The agent must explicitly ask the user to run it.
- **First message in a session:** Detection should run on the user's FIRST substantive message, not on greetings like "hello" or "hi".

## File Locations

- Script: `scripts/skill-gatekeeper.py` (in this skill directory)
- Active skills: `/opt/data/skills/`
- Disabled skills: `/opt/data/skills-disabled/`
- State file: `/opt/data/.skill-gatekeeper-state.json`
