---
name: qq-ops
description: This skill should be used when handling QQ, OneBot, NapCat, group messages, student notifications, channel moderation, or outbound communication workflows.
---

# QQ Operations Skill

## Purpose

Provide safe procedures for handling QQ and OneBot-style channel events while keeping business logic independent from channel protocols.

## Workflow

1. Normalize incoming events into `NormalizedChannelEvent`.
2. Deduplicate by `message_id` before processing.
3. Resolve sender identity and role from trusted business systems.
4. Store attachments in object storage before ingestion.
5. Apply permission checks before reading course or student data.
6. Use approved outbound tools for replies or notifications.
7. Record outbound messages in audit logs.

## Safety Rules

- Do not trust channel nicknames as identity or role.
- Prevent message loops by tagging bot-originated messages.
- Require approval for broad group announcements and student-specific notifications.
- Degrade unsupported rich media to links or plain text with citation.

## References

- Load `references/channel-policy.md` for outbound-message policy details.
