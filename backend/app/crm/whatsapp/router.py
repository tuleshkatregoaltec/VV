import json

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    WebSocket,
)
from fastapi.responses import PlainTextResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import AuthContext, require_active_owner, require_active_subscription
from app.crm.whatsapp import campaigns, live, meta, service
from app.crm.whatsapp.models import (
    WhatsAppAudienceResponse,
    WhatsAppCampaignCreate,
    WhatsAppCampaignDetail,
    WhatsAppCampaignResponse,
    WhatsAppChatResponse,
    WhatsAppMetaNumber,
    WhatsAppNumberResponse,
    WhatsAppNumberWrite,
    WhatsAppReply,
    WhatsAppSendResponse,
    WhatsAppStatusResponse,
    WhatsAppTemplateResponse,
    WhatsAppTemplateSend,
    WhatsAppThreadResponse,
)
from app.postgres import get_db_session

router = APIRouter(prefix="/api/v1/crm/whatsapp", tags=["crm-whatsapp"])

# Meta's WhatsApp id: the customer's number, digits only, with country code.
WaId = Path(pattern=r"^\d{8,15}$")
PhoneNumberId = Path(pattern=r"^\d{5,30}$")


def _auth_ids(context: AuthContext) -> tuple[str, str]:
    return str(context.user.id), str(context.organization.id)


@router.get("/status", response_model=WhatsAppStatusResponse)
async def crm_whatsapp_status(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Whether the signed-in user can message: WhatsApp is connected and they have a number."""
    user_id, organization_id = _auth_ids(context)
    return await service.whatsapp_status(db, organization_id=organization_id, user_id=user_id)


@router.get("/templates", response_model=list[WhatsAppTemplateResponse])
async def crm_whatsapp_templates(context: AuthContext = Depends(require_active_subscription)):
    """The business account's message templates, as Meta reviewed them."""
    return await service.list_templates()


@router.get("/chats", response_model=list[WhatsAppChatResponse])
async def crm_whatsapp_chats(
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """Conversations on the signed-in agent's number, newest first."""
    user_id, organization_id = _auth_ids(context)
    return await service.list_chats(db, organization_id=organization_id, user_id=user_id)


@router.get("/chats/{wa_id}", response_model=WhatsAppThreadResponse)
async def crm_whatsapp_chat(
    wa_id: str = WaId,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await service.chat_thread(
        db, organization_id=organization_id, user_id=user_id, wa_id=wa_id
    )


@router.post("/chats/{wa_id}/reply", response_model=WhatsAppSendResponse)
async def crm_whatsapp_chat_reply(
    payload: WhatsAppReply,
    wa_id: str = WaId,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """A free-form reply from the agent's number, inside the 24-hour window."""
    user_id, organization_id = _auth_ids(context)
    await service.reply_to_chat(
        db, organization_id=organization_id, user_id=user_id, wa_id=wa_id, body=payload.body
    )
    return {"ok": True}


@router.post("/chats/{wa_id}/template", response_model=WhatsAppSendResponse)
async def crm_whatsapp_chat_template(
    payload: WhatsAppTemplateSend,
    wa_id: str = WaId,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """An approved template from the agent's number (to start, or after the window closes)."""
    user_id, organization_id = _auth_ids(context)
    await service.template_to_chat(
        db, organization_id=organization_id, user_id=user_id, wa_id=wa_id, payload=payload
    )
    return {"ok": True}


@router.get("/leads/{enquiry_id}/thread", response_model=WhatsAppThreadResponse)
async def crm_whatsapp_lead_thread(
    enquiry_id: int,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    """The signed-in agent's chat with a lead (Lead › Conversation)."""
    user_id, organization_id = _auth_ids(context)
    return await service.lead_thread(
        db, organization_id=organization_id, user_id=user_id, enquiry_id=enquiry_id
    )


@router.post("/leads/{enquiry_id}/reply", response_model=WhatsAppSendResponse)
async def crm_whatsapp_lead_reply(
    enquiry_id: int,
    payload: WhatsAppReply,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    await service.reply_to_lead(
        db,
        organization_id=organization_id,
        user_id=user_id,
        enquiry_id=enquiry_id,
        body=payload.body,
    )
    return {"ok": True}


@router.post("/leads/{enquiry_id}/template", response_model=WhatsAppSendResponse)
async def crm_whatsapp_lead_template(
    enquiry_id: int,
    payload: WhatsAppTemplateSend,
    context: AuthContext = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    await service.template_to_lead(
        db,
        organization_id=organization_id,
        user_id=user_id,
        enquiry_id=enquiry_id,
        payload=payload,
    )
    return {"ok": True}


# ── Setup (organization owner) ──


@router.get("/numbers", response_model=list[WhatsAppNumberResponse])
async def crm_whatsapp_numbers(
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """The organization's sender numbers and who sends from each."""
    _, organization_id = _auth_ids(context)
    return await service.list_numbers(db, organization_id=organization_id)


@router.put("/numbers/{phone_number_id}", response_model=WhatsAppNumberResponse)
async def crm_whatsapp_save_number(
    payload: WhatsAppNumberWrite,
    phone_number_id: str = PhoneNumberId,
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Register a number by its Meta Phone Number ID: an agent's, or the campaign number."""
    _, organization_id = _auth_ids(context)
    return await service.save_number(
        db, organization_id=organization_id, phone_number_id=phone_number_id, payload=payload
    )


@router.get("/meta/numbers", response_model=list[WhatsAppMetaNumber])
async def crm_whatsapp_meta_numbers(context: AuthContext = Depends(require_active_owner)):
    """The numbers Meta lists under the business account, with their Phone Number IDs."""
    return await service.meta_numbers()


@router.post("/meta/subscribe", response_model=WhatsAppSendResponse)
async def crm_whatsapp_subscribe(context: AuthContext = Depends(require_active_owner)):
    """Subscribe this app to the business account's webhooks (once, during setup)."""
    return {"ok": await service.subscribe_app()}


# ── Campaigns from the campaign number (organization owner) ──


@router.get("/campaign/audience", response_model=WhatsAppAudienceResponse)
async def crm_whatsapp_campaign_audience(
    search: str | None = Query(default=None, max_length=160),
    intent: str | None = Query(default=None, pattern="^(unknown|buy|rent|sell|let)$"),
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Leads a campaign may go to: consent recorded, not opted out, with a WhatsApp number."""
    _, organization_id = _auth_ids(context)
    return await campaigns.audience(
        db, organization_id=organization_id, search=search, intent=intent
    )


@router.get("/campaigns", response_model=list[WhatsAppCampaignResponse])
async def crm_whatsapp_campaigns(
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    _, organization_id = _auth_ids(context)
    return await campaigns.list_campaigns(db, organization_id=organization_id)


@router.post("/campaigns", response_model=WhatsAppCampaignDetail, status_code=201)
async def crm_whatsapp_create_campaign(
    payload: WhatsAppCampaignCreate,
    background: BackgroundTasks,
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Record the campaign and its recipients, then send in the background."""
    user_id, organization_id = _auth_ids(context)
    detail = await campaigns.create_campaign(
        db, organization_id=organization_id, user_id=user_id, payload=payload
    )
    background.add_task(campaigns.run_campaign, detail.id)
    return detail


@router.get("/campaigns/{campaign_id}", response_model=WhatsAppCampaignDetail)
async def crm_whatsapp_campaign(
    campaign_id: int,
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    _, organization_id = _auth_ids(context)
    return await campaigns.campaign_detail(
        db, organization_id=organization_id, campaign_id=campaign_id
    )


@router.post("/campaigns/{campaign_id}/resume", response_model=WhatsAppCampaignDetail)
async def crm_whatsapp_resume_campaign(
    campaign_id: int,
    background: BackgroundTasks,
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Send the recipients an interrupted campaign has not reached yet."""
    _, organization_id = _auth_ids(context)
    detail = await campaigns.resume_campaign(
        db, organization_id=organization_id, campaign_id=campaign_id
    )
    background.add_task(campaigns.run_campaign, detail.id)
    return detail


@router.get("/campaign/chats", response_model=list[WhatsAppChatResponse])
async def crm_whatsapp_campaign_chats(
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Campaign inbox: replies to the campaign number."""
    user_id, organization_id = _auth_ids(context)
    return await campaigns.campaign_chats(db, organization_id=organization_id, user_id=user_id)


@router.get("/campaign/chats/{wa_id}", response_model=WhatsAppThreadResponse)
async def crm_whatsapp_campaign_chat(
    wa_id: str = WaId,
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    user_id, organization_id = _auth_ids(context)
    return await campaigns.campaign_chat(
        db, organization_id=organization_id, user_id=user_id, wa_id=wa_id
    )


@router.post("/campaign/chats/{wa_id}/reply", response_model=WhatsAppSendResponse)
async def crm_whatsapp_campaign_reply(
    payload: WhatsAppReply,
    wa_id: str = WaId,
    context: AuthContext = Depends(require_active_owner),
    db: AsyncSession = Depends(get_db_session),
):
    """Answer a campaign reply from the campaign number, inside the 24-hour window."""
    user_id, organization_id = _auth_ids(context)
    await campaigns.campaign_reply(
        db, organization_id=organization_id, user_id=user_id, wa_id=wa_id, body=payload.body
    )
    return {"ok": True}


# ── Meta webhook (public: the signature is the gate) ──


@router.get("/webhook", response_class=PlainTextResponse)
async def crm_whatsapp_webhook_verify(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge", max_length=200),
):
    """Meta's check when the callback URL is saved: echo the challenge if the token matches."""
    if not meta.verify_subscription(mode, token):
        raise HTTPException(status_code=403, detail="Verification failed")
    return challenge


@router.post("/webhook")
async def crm_whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Incoming messages and delivery statuses. Nothing is read before the signature checks out."""
    raw = await request.body()
    if not meta.verify_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    return {"ok": True, **await service.receive_webhook(db, payload)}


# ── Live updates (the token is the first frame; see live.py) ──


@router.websocket("/live")
async def crm_whatsapp_live(websocket: WebSocket):
    """Pushes `chat.changed` for the chats the signed-in user can see, as webhooks arrive."""
    await live.serve(websocket)
