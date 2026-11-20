#!/usr/bin/env bash
# Založí štítky agentního workflow v GitHub repu (idempotentně). Spustit jednou: tools/setup_agent_labels.sh [owner/repo]
set -euo pipefail
REPO=${1:-papro-thc/EnvoCAD}
label() { gh label create "$1" -R "$REPO" --color "$2" --description "$3" --force; }
label agent-task        "c5def5" "Úkol pro agenta (ze šablony), zatím nepřipravený"
label agent-ready       "0e8a16" "Zadání hotové – noční agent ho smí vzít"
label agent-in-progress "fbca04" "Agent na issue právě pracuje"
label agent-question    "d876e3" "Agent se ptá – odpověz v komentáři a štítek odeber"
label agent-failed      "b60205" "Agent nedokončil / CI neprošlo – rozhoduje člověk"
label agent             "1d76db" "PR otevřený agentem"
