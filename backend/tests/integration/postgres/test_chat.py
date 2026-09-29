from uuid import uuid4

from app.chat.service import (
    add_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_conversation_messages,
)


async def test_conversation_ownership_and_message_json_survive_real_commits(pg_session):
    owner = str(uuid4())
    conversation = await create_conversation(pg_session, owner, str(uuid4()))
    conversation_id = conversation.id
    payload = {
        "total_tokens": 12,
        "artifacts": [
            {"id": "tool-1", "type": "chart", "data": {"points": [], "legacy": {"x": 1}}}
        ],
    }
    await add_message(pg_session, conversation_id, "user", "Preserve this conversation")
    await add_message(pg_session, conversation_id, "assistant", "Result", payload)
    pg_session.expire_all()
    messages = await get_conversation_messages(pg_session, conversation_id)
    assert [item.role for item in messages] == ["user", "assistant"]
    assert messages[1].meta_data == payload
    assert await get_conversation(pg_session, conversation_id, "another-user") is None
    assert await delete_conversation(pg_session, conversation_id, "another-user") is False
    assert await delete_conversation(pg_session, conversation_id, owner) is True
    assert await get_conversation_messages(pg_session, conversation_id) == []
