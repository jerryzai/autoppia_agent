"""Multi-layer prompt construction combining best strategies from all top agents.

Layer architecture:
1. System prompt: rigid action schema + JSON-only enforcement
2. Task context: prompt + classification + website + step counter
3. Constraints block: parsed constraints formatted for LLM
4. Credentials: extracted credential values
5. Website hints + playbook: domain knowledge
6. Warnings: loop/stuck detection
7. Action history: recent steps with outcomes
8. Filled fields: prevent re-filling
9. DOM digest: page structure summary (early steps only)
10. Page IR: interactive elements with context
11. Final instruction: action request
"""
from __future__ import annotations


def build_system_prompt() -> str:
    return """You are an expert web automation agent. You analyze web pages and choose precise browser actions to complete tasks.

RESPONSE FORMAT: Return a SINGLE JSON object. No markdown, no explanation, no code fences.

ACTIONS:
  {"action": "click", "candidate_id": N}
  {"action": "type", "candidate_id": N, "text": "value"}
  {"action": "select_option", "candidate_id": N, "text": "option text"}
  {"action": "navigate", "url": "http://localhost:PORT/path?seed=X"}
  {"action": "scroll", "direction": "down"}
  {"action": "scroll", "direction": "up"}
  {"action": "done"}

RULES:
1. candidate_id MUST match an [N] from the Interactive elements list.
2. For login: use <username> and <password> as text values unless specific credentials given.
3. For navigate: ALWAYS keep the ?seed= parameter from the current URL.
4. For type: type the EXACT value from constraints. Respect equals/contains/not_contains rules.
5. For select_option: use the exact option text shown in options=[...].
6. Choose the SINGLE most effective action. Prefer direct actions over exploration.
7. If the task is complete, return {"action": "done"}.
8. NEVER repeat an action that already failed or was already done.

JSON ONLY. No explanation."""


def build_user_prompt(
    *,
    prompt: str,
    page_ir_text: str,
    step_index: int,
    task_type: str,
    action_history: list[str],
    website: str | None,
    website_hint: str = "",
    constraints_block: str = "",
    credentials_info: str = "",
    playbook: str = "",
    loop_warning: str | None = None,
    stuck_warning: str | None = None,
    filled_fields: set[str] | None = None,
    dom_digest: str = "",
) -> str:
    parts: list[str] = []

    # --- Core task context ---
    parts.append(f"TASK: {prompt}")

    site_line = f"SITE: {website or 'unknown'}"
    if website_hint:
        site_line += f" — {website_hint}"
    parts.append(site_line)

    parts.append(f"TYPE: {task_type}  |  STEP: {step_index} of 12")

    # --- Urgency signal ---
    remaining = max(1, 12 - step_index)
    if remaining <= 3:
        parts.append(f"⚠ ONLY {remaining} STEPS LEFT — take the most direct action NOW.")

    # --- Constraints ---
    if constraints_block:
        parts.append("")
        parts.append(constraints_block)

    # --- Credentials ---
    if credentials_info:
        parts.append(f"\nCREDENTIALS: {credentials_info}")

    # --- Playbook ---
    if playbook:
        parts.append(f"\nPLAYBOOK: {playbook}")

    # --- Warnings ---
    if loop_warning:
        parts.append(f"\n⚠ {loop_warning}")
    if stuck_warning:
        parts.append(f"\n⚠ {stuck_warning}")

    # --- Action history ---
    if action_history:
        history_text = "\n".join(f"  - {h}" for h in action_history)
    else:
        history_text = "  None yet"
    parts.append(f"\nHISTORY:\n{history_text}")

    # --- Filled fields ---
    if filled_fields:
        parts.append(f"\nALREADY FILLED: {', '.join(sorted(filled_fields))}")

    # --- DOM digest (early steps for orientation) ---
    if dom_digest and step_index <= 1:
        parts.append(f"\nPAGE STRUCTURE:\n{dom_digest}")

    # --- Page IR (always) ---
    parts.append(f"\nPAGE ELEMENTS:\n{page_ir_text}")

    # --- Final instruction ---
    parts.append("\nChoose ONE action to make progress. Return JSON only.")

    return "\n".join(parts)
