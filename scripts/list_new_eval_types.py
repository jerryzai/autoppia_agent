#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    data = json.loads(Path("data/leaderboard_tasks_all_pages.json").read_text(encoding="utf-8"))
    tasks = data.get("tasks") or []
    page1 = tasks[:100]
    p1_types = {str(t.get("useCase") or "") for t in page1 if t.get("useCase")}
    all_types = {str(t.get("useCase") or "") for t in tasks if t.get("useCase")}
    new_types = sorted(all_types - p1_types)

    out = Path("data/new_evaluation_types.txt")
    out.write_text("\n".join(new_types) + "\n", encoding="utf-8")
    print(f"page1 types: {len(p1_types)}")
    print(f"all pages types: {len(all_types)}")
    print(f"new vs page1: {len(new_types)}")
    print(f"wrote: {out.as_posix()}")


if __name__ == "__main__":
    main()

