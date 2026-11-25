"""The CRM Operations Assistant: CRM records and CRM-supported changes in chat.

Reads follow the CRM's own role and team visibility; changes are proposed through
``app.assistant_actions`` and applied only after the user confirms. Market research is not
part of this assistant.

Modules: ``records`` (role-scoped CRM reads), ``models``/``repository`` (their schema and
queries), ``crm_tools``/``connector_tools`` (the model's read tools), ``workflows`` (CRM
specialists and change proposals), ``agent``/``routing`` (the turn's coordinator),
``capabilities`` (shared instructions), ``service``/``router`` (the chat turn and its API).
"""

from app.crm.assistant.records import has_current_access, query_my_records, same_team

__all__ = ["has_current_access", "query_my_records", "same_team"]
