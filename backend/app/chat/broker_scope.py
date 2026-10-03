"""Turn-local preservation of explicit broker matching constraints, in addition to stored CRM criteria."""

from fastapi import HTTPException

from app.crm.broker_models import BrokerRequirements


class BrokerTurnScope:
    def __init__(self):
        self.requirements: dict[int, dict] = {}
        self.scopes: dict[int, str] = {}

    def apply(self, request):
        enquiry_id = getattr(request, "enquiry_id", None)
        if enquiry_id is None:
            return request
        scope = request.scope
        if enquiry_id in self.scopes and self.scopes[enquiry_id] != scope:
            raise HTTPException(422, "Keep the authorized enquiry scope unchanged during this turn")
        self.scopes[enquiry_id] = scope
        if not hasattr(request, "requirements"):
            return request
        explicit = request.requirements
        existing = self.requirements.get(enquiry_id, {})
        if explicit is not None:
            provided = explicit.model_dump(exclude_unset=True, exclude_none=True)
            if any(key in existing and existing[key] != value for key, value in provided.items()):
                raise HTTPException(
                    422,
                    "Matching requirements are frozen for this turn; do not relax or replace requested constraints",
                )
            existing = {**existing, **provided}
            self.requirements[enquiry_id] = existing
        return request.model_copy(
            update={
                "requirements": BrokerRequirements.model_validate(existing) if existing else None
            }
        )

    def for_enquiry(self, enquiry_id):
        values = self.requirements.get(enquiry_id)
        return BrokerRequirements.model_validate(values) if values else None


def verify_quotation_charges(charges, user_instruction: str | None, missing_charges=None):
    """Fees require explicit broker text, not numbers introduced by a model/tool result.

    This deliberately supports a small unambiguous input syntax instead of guessing
    financial instructions. REST fields are explicit broker inputs; chat uses these lines.
    """
    import re
    from decimal import Decimal

    if missing_charges == [] and not re.search(
        r"(?im)(?:^|[;\n])\s*Charges complete:\s*yes\s*(?:$|[;\n])", user_instruction or ""
    ):
        raise HTTPException(
            422,
            'Keep unknown charges listed, or explicitly state "Charges complete: yes" when every applicable charge has been supplied.',
        )
    for charge in charges:
        if charge.status == "missing":
            continue
        pattern = (
            re.escape(charge.label)
            + r"\s*(?:\((known|estimate)\))?\s*:\s*(AED\s*)?"
            + r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(%)?(?![\d.])"
        )
        entries = list(re.finditer(pattern, user_instruction or "", re.IGNORECASE))
        valid = []
        for entry in entries:
            status, currency, amount, percent = entry.groups()
            status = (status or "known").casefold()
            expected = charge.percent_of_asking if percent else charge.amount
            if (
                (currency or percent)
                and expected is not None
                and Decimal(amount.replace(",", "")) == expected
                and status == charge.status
            ):
                valid.append(entry)
        if len(entries) != 1 or len(valid) != 1:
            raise HTTPException(
                422,
                'Quotation fees need explicit values in the current broker message, for example "Brokerage: 2%; Administration (estimate): AED 500.50". Do not invent fees or reuse values from tool output.',
            )
