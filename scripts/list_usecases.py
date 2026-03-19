#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path


def extract_playbook_keys(agent_py: str) -> set[str]:
    m = re.search(r"_TASK_PLAYBOOKS:\s*Dict\[str,\s*str\]\s*=\s*\{", agent_py)
    if not m:
        return set()
    start = m.end() - 1
    level = 0
    end = start
    for i, ch in enumerate(agent_py[start:], start):
        if ch == "{":
            level += 1
        elif ch == "}":
            level -= 1
            if level == 0:
                end = i
                break
    block = agent_py[start : end + 1]
    return set(re.findall(r'^\s*"([A-Z0-9_]+)"\s*:\s*\(', block, flags=re.MULTILINE))


def main() -> None:
    data = json.loads(Path("data/leaderboard_tasks_all_pages.json").read_text(encoding="utf-8"))
    tasks = data.get("tasks") or []
    usecases = sorted({str(t.get("useCase") or "") for t in tasks if t.get("useCase")})
    print(f"total tasks: {len(tasks)}")
    print(f"unique useCases: {len(usecases)}")

    agent_py = Path("agent.py").read_text(encoding="utf-8")
    keys = extract_playbook_keys(agent_py)
    missing = [u for u in usecases if u not in keys]
    print(f"useCases without explicit playbook key: {len(missing)}")
    for u in missing:
        print(u)


if __name__ == "__main__":
    main()

