# Channel Policy

- Normalize every inbound channel event before entering the orchestrator.
- Do not emit private student information into a group conversation.
- Require approval for mass notifications.
- Include source, channel, conversation ID, and message ID in audit metadata.
- Prefer official QQ Bot for compliance-oriented deployments; use OneBot/NapCat only behind a channel adapter boundary.
