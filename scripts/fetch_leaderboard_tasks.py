#!/usr/bin/env python3
"""Download all task prompts from the Autoppia leaderboard API (paginated).

Usage:
  python scripts/fetch_leaderboard_tasks.py
  python scripts/fetch_leaderboard_tasks.py --out data/leaderboard_tasks.json

Use the output to review useCase + prompt pairs and tune agent playbooks.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

BASE = "https://api-leaderboard.autoppia.com/api/v1/tasks/search"


def fetch_page(page: int, limit: int, success_mode: str) -> dict:
    q = f"successMode={success_mode}&page={page}&limit={limit}&includeDetails=false"
    url = f"{BASE}?{q}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="", help="Write combined JSON to this file")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--success-mode", default="all", choices=["all", "success", "failed"])
    args = ap.parse_args()

    all_tasks: list[dict] = []
    page = 1
    while True:
        data = fetch_page(page, args.limit, args.success_mode)
        if not data.get("success"):
            print(json.dumps(data, indent=2), file=sys.stderr)
            sys.exit(1)
        chunk = (data.get("data") or {}).get("tasks") or []
        if not chunk:
            break
        all_tasks.extend(chunk)
        if len(chunk) < args.limit:
            break
        page += 1

    # Compact view: useCase, prompt, status, score
    summary = [
        {
            "useCase": t.get("useCase"),
            "prompt": t.get("prompt"),
            "status": t.get("status"),
            "score": t.get("score"),
        }
        for t in all_tasks
    ]

    out = {"total": len(all_tasks), "tasks": all_tasks, "summary": summary}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"Wrote {len(all_tasks)} tasks to {args.out}")
    else:
        print(json.dumps(summary[:20], indent=2, ensure_ascii=False))
        print(f"\n... ({len(all_tasks)} total). Use --out file.json for full dump.")


if __name__ == "__main__":
    main()
