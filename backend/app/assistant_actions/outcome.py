"""What the assistant says about a proposed action comes from the server, never the model.

The model writes its answer while a proposal is still awaiting confirmation, and its text is
stored. The action itself moves on afterwards (confirmed, delivered, failed), so whenever the
answer is shown it is rebuilt from the action's current, authoritative status: one server
sentence per action, followed by the model's text with any of its own claims about whether the
action is done, pending or failed removed. The card and the message can then never disagree.
"""

import re

from app.assistant_actions.models import ActionProposalResponse

# A sentence that speaks about an action's state: done ("I've added it", "it was saved",
# "has been booked"), not done ("nothing was added", "not yet booked") or the proposal itself
# ("this is only a proposal", "awaiting your confirmation", "please confirm").
_DONE_WORDS = (
    r"add(?:ed)?|book(?:ed)?|schedul(?:ed|e)|sav(?:ed|e)|creat(?:ed|e)|sync(?:ed)?|sent|send|"
    r"updat(?:ed|e)|put|plac(?:ed|e)|complet(?:ed|e)|done|confirmed|finished|set up|"
    r"(?:re)?assign(?:ed)?|unassign(?:ed)?|mov(?:ed|e)|transferred|released|logged|changed|"
    r"remov(?:ed|e)|delet(?:ed|e)|promoted|made|reschedul(?:ed|e)|cancel(?:l?ed)?"
)
_OUTCOME_CLAIM = re.compile(
    rf"""
    \b(?:i|i've|i\ have|i'll|we've|we\ have|it's|it\ is|it\ has|it\ was|this\ is|that's|
         (?:has|have|had)\ (?:now\ )?been|was|were|is\ now|are\ now|successfully|already\ been)\b
       [^.!?\n]*\b(?:{_DONE_WORDS})\b
    | \b(?:is|are)\ now\b[^.!?\n]*\b(?:supervisors?|managers?|agents?|members?)\b
    | \b(?:nothing|not|n't|no\ event|no\ meeting|no\ changes?)\b[^.!?\n]*\b(?:{_DONE_WORDS}|changed)\b
    | \b(?:proposal|proposed|propose|awaiting|pending|queued|confirmation|confirm)\b
    | ^\s*(?:done|all\ set|all\ done|success(?:ful)?)\s*[.!]*\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")


def strip_outcome_claims(text: str) -> str:
    """The model's text without sentences claiming whether an action happened."""
    kept = [
        part
        for part in _SENTENCE.findall(text or "")
        if part.strip() and not _OUTCOME_CLAIM.search(part)
    ]
    return re.sub(r"[ \t]+\n", "\n", "".join(kept)).strip()


def status_sentence(action: ActionProposalResponse) -> str:
    """The authoritative status of one action, in words that match its card."""
    title = action.title
    detail = (action.result or {}).get("message")
    detail = detail if isinstance(detail, str) and detail.strip() else None
    if action.preview.get("available") is False:
        return f"{title}: no longer available. Nothing further will happen; ask for a new proposal."
    status = action.status
    if status == "awaiting_confirmation":
        return (
            f"{title}: awaiting your confirmation. Nothing has been saved, booked or sent yet; "
            "it happens only after you confirm it below."
        )
    if status == "queued":
        return f"{title}: confirmed and in progress. Completion is not confirmed yet."
    if status == "unknown":
        return (
            f"{title}: confirmed, but the outcome is not known yet. Check before repeating it; "
            "do not assume it was added."
        )
    if status == "succeeded":
        return f"{title}: completed. {detail}" if detail else f"{title}: completed."
    if status == "partially_succeeded":
        return f"{title}: partly completed. {detail}" if detail else f"{title}: partly completed."
    if status == "failed":
        reason = f" {detail}" if detail else ""
        return f"{title}: failed.{reason} It is not confirmed as done."
    if status == "not_connected":
        return f"{title}: not done. The provider is not connected; nothing was sent or booked."
    if status == "cancelled":
        return f"{title}: cancelled. Nothing was changed."
    if status == "expired":
        return f"{title}: expired before confirmation. Nothing was changed."
    return f"{title}: status unavailable. Do not assume it was done."


def compose(answer: str, actions: list[ActionProposalResponse]) -> str:
    """The answer to show: server status lines first, then the model's remaining text."""
    if not actions:
        return answer
    lines = "\n".join(status_sentence(action) for action in actions)
    rest = strip_outcome_claims(answer)
    return f"{lines}\n\n{rest}" if rest else lines


def model_context(actions: list[ActionProposalResponse]) -> list[dict]:
    """Structured, current action outcomes for the next turn's model context."""
    return [
        {
            "action": action.title,
            "status": action.status
            if action.preview.get("available") is not False
            else "unavailable",
            "server_statement": status_sentence(action),
        }
        for action in actions
    ]
