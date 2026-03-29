"""Main agent orchestrator - the decision pipeline.

Architecture: graduated complexity cascade
1. Quick click shortcuts (regex → known element ID)       ~5% tasks, 0 LLM calls
2. Search shortcuts (type into known search input)        ~10% tasks, 0 LLM calls
3. Form shortcuts (login/reg/contact/logout detection)    ~25% tasks, 0 LLM calls
4. LLM decision (full prompt with context)                ~60% tasks, 1 LLM call
5. Fallback (scroll/wait)                                 safety net

Key innovations over individual agents:
- Combined shortcut patterns from all three top agents
- Enhanced constraint parsing with credential extraction
- Context-per-candidate for better LLM disambiguation
- DOM digest on early steps for page orientation
- Adaptive stuck recovery (scroll → click → navigate)
- Login-then-action compound task support via state tracking
"""
from __future__ import annotations
import logging

from config import (
    detect_website,
    WEBSITE_HINTS,
    TASK_PLAYBOOKS,
)
from classifier import classify_task_type, classify_shortcut_type
from constraint_parser import (
    parse_constraints,
    format_constraints_block,
    extract_credentials,
)
from html_parser import prune_html, extract_candidates, build_page_ir, build_dom_digest
from navigation import extract_seed
from shortcuts import try_quick_click, try_search_shortcut, try_shortcut
from state_tracker import StateTracker
from llm_client import LLMClient
from prompts import build_system_prompt, build_user_prompt
from action_builder import parse_llm_response, build_iwa_action, WAIT_ACTION

logger = logging.getLogger(__name__)

_llm_client: LLMClient | None = None


def _get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def _record_actions(task_id: str, actions: list[dict], url: str, step: int) -> None:
    """Record all returned actions into state tracker."""
    for i, act in enumerate(actions):
        sel_val = ""
        sel = act.get("selector", {})
        if isinstance(sel, dict):
            sel_val = sel.get("value", "")
        text = act.get("text", "")
        StateTracker.record_action(task_id, act.get("type", ""), sel_val, url, step + i, text)
        if act.get("type") == "TypeAction" and sel_val:
            StateTracker.record_filled_field(task_id, sel_val)


async def handle_act(
    task_id: str | None,
    prompt: str | None,
    url: str | None,
    snapshot_html: str | None,
    screenshot: str | None,
    step_index: int | None,
    web_project_id: str | None,
    history: list | None = None,
) -> list[dict]:
    """Main entry point called by /act endpoint."""
    if not prompt or not url:
        logger.warning("Missing prompt or url")
        return [WAIT_ACTION]

    step = step_index or 0
    task = task_id or "unknown"
    website = web_project_id or detect_website(url)
    seed = extract_seed(url)
    state = StateTracker.get_or_create(task)

    # Initialize on step 0
    if step == 0:
        state.constraints = parse_constraints(prompt)
        state.task_type = classify_task_type(prompt)
        state.login_done = False
        state.history.clear()
        state.filled_fields.clear()
        StateTracker.auto_cleanup()

    # ===================================================================
    # STAGE 1: Quick click shortcuts (no HTML parsing needed)
    # ===================================================================
    quick = try_quick_click(prompt, url, seed, step)
    if quick is not None:
        logger.info(f"Quick click: {len(quick)} actions")
        _record_actions(task, quick, url, step)
        return quick

    # ===================================================================
    # STAGE 2: Search shortcut
    # ===================================================================
    search = try_search_shortcut(prompt, website)
    if search is not None:
        logger.info(f"Search shortcut: {len(search)} actions")
        _record_actions(task, search, url, step)
        return search

    # ===================================================================
    # Parse HTML and extract candidates
    # ===================================================================
    if snapshot_html and snapshot_html.strip():
        soup = prune_html(snapshot_html)
        candidates = extract_candidates(soup)
    else:
        soup = None
        candidates = []

    # ===================================================================
    # STAGE 3: Form-based shortcuts (login/reg/contact/logout)
    # ===================================================================
    shortcut_type = classify_shortcut_type(prompt)

    # For login_then_action: do login shortcut on early steps, then fall to LLM
    if state.task_type == "login_then_action" and not state.login_done:
        shortcut_type = "login"

    if shortcut_type and soup and candidates:
        shortcut_actions = try_shortcut(shortcut_type, candidates, soup, step)
        if shortcut_actions is not None:
            logger.info(f"Shortcut '{shortcut_type}': {len(shortcut_actions)} actions")
            _record_actions(task, shortcut_actions, url, step)
            # Mark login done for compound tasks
            if shortcut_type == "login":
                StateTracker.mark_login_done(task)
            return shortcut_actions

    # ===================================================================
    # No candidates = page still loading or empty
    # ===================================================================
    if not candidates:
        logger.warning("No candidates - page may still be loading")
        StateTracker.record_action(task, "WaitAction", "", url, step)
        return [{"type": "WaitAction", "time_seconds": 2}]

    # ===================================================================
    # STAGE 4: Stuck recovery (before LLM to save tokens)
    # ===================================================================
    loop_warning = StateTracker.detect_loop(task, url)
    stuck_warning = StateTracker.detect_stuck(task, url)

    if stuck_warning and step >= 3:
        recent = state.history[-2:] if len(state.history) >= 2 else []
        all_scrolls = all(a.action_type == "ScrollAction" for a in recent) if recent else False
        if not all_scrolls:
            logger.info("Stuck recovery: auto-scroll")
            StateTracker.record_action(task, "ScrollAction", "", url, step)
            return [{"type": "ScrollAction", "down": True}]

    # ===================================================================
    # STAGE 5: Build page IR and context
    # ===================================================================
    page_ir = build_page_ir(soup, url, candidates)
    page_ir_text = page_ir.raw_text

    # DOM digest for early steps (helps LLM understand page layout)
    dom_digest = ""
    if soup and step <= 1:
        dom_digest = build_dom_digest(soup)

    # Prepare prompt layers
    action_history = StateTracker.get_recent_history(task, count=4)
    filled_fields = StateTracker.get_filled_fields(task)
    constraints_block = format_constraints_block(state.constraints)
    website_hint = WEBSITE_HINTS.get(website, "") if website else ""
    playbook = TASK_PLAYBOOKS.get(state.task_type, TASK_PLAYBOOKS.get("general", ""))

    # Credential info
    creds = extract_credentials(prompt)
    cred_parts = []
    if creds.get("username"):
        cred_parts.append(f"username={creds['username']}")
    if creds.get("password"):
        cred_parts.append(f"password={creds['password']}")
    credentials_info = ", ".join(cred_parts) if cred_parts else ""

    # ===================================================================
    # STAGE 6: LLM decision
    # ===================================================================
    try:
        client = _get_llm_client()
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(
            prompt=prompt,
            page_ir_text=page_ir_text,
            step_index=step,
            task_type=state.task_type,
            action_history=action_history,
            website=website,
            website_hint=website_hint,
            constraints_block=constraints_block,
            credentials_info=credentials_info,
            playbook=playbook,
            loop_warning=loop_warning,
            stuck_warning=stuck_warning,
            filled_fields=filled_fields,
            dom_digest=dom_digest,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        llm_response = client.chat(task_id=task, messages=messages)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return [WAIT_ACTION]

    # ===================================================================
    # STAGE 7: Parse and validate response
    # ===================================================================
    decision = parse_llm_response(llm_response)

    if decision is None:
        # Retry once with stronger instruction
        logger.warning(f"Parse failed, retrying. Response: {llm_response[:200]}")
        try:
            messages.append({"role": "assistant", "content": llm_response})
            messages.append({
                "role": "user",
                "content": (
                    "Your response was NOT valid JSON. "
                    "Return ONLY a JSON object like {\"action\": \"click\", \"candidate_id\": 0}. "
                    "No markdown, no commentary, no code fences."
                ),
            })
            retry_response = client.chat(task_id=task, messages=messages)
            decision = parse_llm_response(retry_response)
        except Exception as e:
            logger.error(f"LLM retry failed: {e}")

    if decision is None:
        logger.warning("All parse attempts failed")
        # Fallback: scroll on later steps, click first candidate on early steps
        if step <= 3 and candidates:
            fallback = {"type": "ClickAction", "selector": candidates[0].selector.model_dump()}
        else:
            fallback = {"type": "ScrollAction", "down": True}
        _record_actions(task, [fallback], url, step)
        return [fallback]

    # ===================================================================
    # STAGE 8: Build action
    # ===================================================================
    action = build_iwa_action(decision, page_ir.candidates, url, seed)
    action_type = action.get("type", "unknown")

    # Block NavigateAction on step 0 (already on correct page)
    if step == 0 and action_type == "NavigateAction":
        logger.info("Blocked NavigateAction on step 0 → scroll instead")
        action = {"type": "ScrollAction", "down": True}
        action_type = "ScrollAction"

    # Done signal
    if action_type == "IdleAction":
        logger.info("Task marked done by LLM")
        _record_actions(task, [action], url, step)
        return []

    logger.info(f"LLM action: {action_type}")
    _record_actions(task, [action], url, step)
    return [action]
