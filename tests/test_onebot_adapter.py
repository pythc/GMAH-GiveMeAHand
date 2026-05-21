from agent_workflow.channels.onebot.adapter import OneBotAdapter, is_archive_attachment
from agent_workflow.channels.onebot.models import (
    OneBotEvent,
    OneBotFileInfo,
    OneBotMessageSegment,
    OneBotSender,
)


def test_onebot_adapter_normalizes_group_message_with_file_segment() -> None:
    event = OneBotEvent(
        post_type="message",
        message_type="group",
        time=1_700_000_000,
        group_id=123,
        user_id=456,
        message_id=789,
        sender=OneBotSender(nickname="Alice", card="小明", role="student"),
        message=[
            OneBotMessageSegment(type="text", data={"text": "请分析这个压缩包"}),
            OneBotMessageSegment(
                type="file",
                data={
                    "file": "project.zip",
                    "url": "file:///tmp/project.zip",
                    "size": 1024,
                },
            ),
        ],
    )

    normalized = OneBotAdapter().normalize(event)

    assert normalized.conversation_id == "group:123"
    assert normalized.sender.display_name == "小明"
    assert normalized.content.text == "请分析这个压缩包"
    assert normalized.content.attachments[0].name == "project.zip"
    assert is_archive_attachment(normalized.content.attachments[0]) is True


def test_onebot_adapter_normalizes_self_sent_private_message() -> None:
    event = OneBotEvent(
        post_type="message_sent",
        message_type="private",
        time=1_700_000_000,
        user_id=456,
        message_id=789,
        sender=OneBotSender(nickname="Bot"),
        message="测试消息",
    )

    normalized = OneBotAdapter().normalize(event)

    assert normalized.conversation_id == "private:456"
    assert normalized.content.text == "测试消息"


def test_onebot_adapter_normalizes_group_upload_notice() -> None:
    event = OneBotEvent(
        post_type="notice",
        notice_type="group_upload",
        time=1_700_000_000,
        group_id=123,
        user_id=456,
        file=OneBotFileInfo(id="file-1", name="paper.pdf", size=2048, url="http://file"),
    )

    normalized = OneBotAdapter().normalize(event)

    assert normalized.message_id == "file-1"
    assert normalized.content.attachments[0].mime == "application/pdf"
