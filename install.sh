#!/usr/bin/env bash
# Install Skill Gatekeeper for Hermes Agent
# Usage: ./install.sh [HERMES_HOME]
#
# The gatekeeper reads HERMES_HOME from the environment.
# If not set, it defaults to /opt/data.
# Set it persistently:
#   echo 'export HERMES_HOME=/path/to/hermes' >> ~/.bashrc

set -e

HERMES_HOME="${1:-${HERMES_HOME:-/opt/data}}"
SCRIPTS_DIR="$HERMES_HOME/scripts"
SKILLS_DIR="$HERMES_HOME/skills"
SCRIPT_DIR="$(dirname "$(realpath "$0")")"

echo "Installing Skill Gatekeeper..."
echo "  Hermes home: $HERMES_HOME"
echo ""

# 1. Copy the gatekeeper script
echo "  → Copying skill-gatekeeper.py to $SCRIPTS_DIR/"
mkdir -p "$SCRIPTS_DIR"
cp "$SCRIPT_DIR/skill-gatekeeper.py" "$SCRIPTS_DIR/skill-gatekeeper.py"
chmod +x "$SCRIPTS_DIR/skill-gatekeeper.py"

# 2. Install the skill-mode-switch skill
echo "  → Installing skill-mode-switch to $SKILLS_DIR/devops/"
mkdir -p "$SKILLS_DIR/devops/skill-mode-switch"
cp "$SCRIPT_DIR/skill-mode-switch/SKILL.md" "$SKILLS_DIR/devops/skill-mode-switch/SKILL.md"

echo ""
echo "✓ Installed."
echo ""
echo "If HERMES_HOME is not /opt/data, set it:"
echo "  export HERMES_HOME=$HERMES_HOME"
echo ""
echo "Run /reload-skills in Hermes to activate."
echo ""
echo "Quick test:"
echo "  HERMES_HOME=$HERMES_HOME python3 $SCRIPTS_DIR/skill-gatekeeper.py --list"
echo ""
echo ""
echo "── Setting up persistent default mode (optional) ──"
echo ""
echo "After install, set your preferred mode to survive restarts:"
echo ""
echo "  # 1. Choose your default mode"
echo "  HERMES_HOME=$HERMES_HOME python3 $SCRIPTS_DIR/skill-gatekeeper.py --set-default dev"
echo ""
echo "  # 2. Add to cron so gateway restarts re-trim within 30min"
echo "  (crontab -l 2>/dev/null; echo \"*/30 * * * * HERMES_HOME=$HERMES_HOME python3 $SCRIPTS_DIR/skill-gatekeeper.py --boot\") | crontab -"
echo ""
echo "  # 3. Verify"
echo "  python3 $SCRIPTS_DIR/skill-gatekeeper.py --boot"
echo "  python3 $SCRIPTS_DIR/skill-gatekeeper.py --list"
