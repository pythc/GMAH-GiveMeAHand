# 渠道适配规范

## 目标

业务核心不依赖 QQ、OneBot、Webhook、邮件或其他具体渠道。所有入口先转为统一事件模型，再进入会话编排。

## 统一事件模型

```json
{
  "channel": "qq",
  "platform_protocol": "onebot_v11",
  "conversation_id": "group:123456",
  "message_id": "evt_abc",
  "sender": {
    "user_id": "u_001",
    "display_name": "张三",
    "role": "student"
  },
  "content": {
    "text": "请总结这份 PDF",
    "attachments": [
      {
        "type": "file",
        "mime": "application/pdf",
        "uri": "oss://bucket/file.pdf"
      }
    ]
  },
  "timestamp": "2026-05-18T10:30:00+09:00"
}
```

## 适配要求

- 消息必须有唯一 `message_id`，用于去重和审计。
- 附件必须先落对象存储或可信临时 URI，再交给摄取流程。
- 群聊、私聊、邮件线程、Webhook 事件都要映射到 `conversation_id`。
- 发送者角色需要由业务权限系统补全，不信任渠道原始昵称。
- 出站消息必须经过风控、权限和审计。

## QQ 接入建议

- 合规优先：官方 QQ Bot。
- 灵活性优先：OneBot/NapCat 生态。
- 遗留兼容：go-cqhttp 仅作为迁移路径，不作为新系统主线。
