from datetime import datetime

from agent_workflow.channels.events import (
    Attachment,
    AttachmentType,
    MessageContent,
    NormalizedChannelEvent,
    Sender,
)


def test_normalized_channel_event() -> None:
    event = NormalizedChannelEvent(
        channel="qq",
        platform_protocol="onebot_v11",
        conversation_id="group:123456",
        message_id="evt-1",
        sender=Sender(user_id="u-1", display_name="张三", role="student"),
        content=MessageContent(
            text="请总结 PDF",
            attachments=[
                Attachment(
                    type=AttachmentType.FILE,
                    mime="application/pdf",
                    uri="oss://bucket/file.pdf",
                )
            ],
        ),
        timestamp=datetime.fromisoformat("2026-05-18T10:30:00+09:00"),
    )
    assert event.sender.role == "student"
    assert event.content.attachments[0].type == AttachmentType.FILE
