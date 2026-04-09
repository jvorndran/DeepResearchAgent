"""Single source of truth for text shown in the home chat UI."""

from langchain_core.tools import tool


@tool
def emit_chat_message(markdown: str) -> str:
    """
    Emit the only markdown the end-user should read in the chat UI for this assistant turn.

    Call exactly once per user-visible reply, before `task()` or other tools (except when asking questions only).
    Put intake questions as a short intro line plus bullet list.
    When intake is complete and you are about to delegate with `task()`, your markdown MUST tell the user to click
    **Commence Deep Research** in the UI to approve and begin — see system prompt for required wording.
    Do not paste internal checklists, skills, or long Phase templates here.
    """
    return "Message recorded for the chat UI."
