"""OneBot HTTP API client for replying to QQ/NapCat conversations."""

from typing import Any

import httpx
from pydantic import BaseModel, Field, SecretStr

from agent_workflow.channels.base import ChannelClient


class OneBotClientError(RuntimeError):
    """Raised when OneBot HTTP API returns an error."""


class OneBotSendResult(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)


class OneBotHttpClient(ChannelClient):
    """Small OneBot v11 HTTP action client.

    Implements the ChannelClient ABC for the QQ/OneBot protocol.
    NapCat 通常可开启 HTTP 服务；不同部署可能是正向 HTTP 或反向 WebSocket。
    """

    def __init__(
        self,
        *,
        base_url: str,
        access_token: SecretStr | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def send_group_msg(
        self, group_id: str, message: str, reply_to: str | None = None
    ) -> OneBotSendResult:
        """Send a group message, optionally quoting a previous message."""
        if reply_to:
            segments: list[dict[str, Any]] = [
                {"type": "reply", "data": {"id": str(reply_to)}},
                {"type": "text", "data": {"text": message}},
            ]
            return self._action(
                "send_group_msg", {"group_id": int(group_id), "message": segments}
            )
        return self._action("send_group_msg", {"group_id": group_id, "message": message})

    def send_private_msg(self, user_id: str, message: str) -> OneBotSendResult:
        return self._action("send_private_msg", {"user_id": user_id, "message": message})

    def send_group_file_base64(
        self, group_id: str, data: bytes, name: str
    ) -> OneBotSendResult:
        """Send a file to a group using base64 encoding in message segment."""
        import base64 as _b64

        b64 = _b64.b64encode(data).decode("ascii")
        message = [{"type": "file", "data": {"file": f"base64://{b64}", "name": name}}]
        return self._action(
            "send_group_msg", {"group_id": int(group_id), "message": message}
        )

    def send_private_file_base64(
        self, user_id: str, data: bytes, name: str
    ) -> OneBotSendResult:
        """Send a file to a private chat using base64 encoding."""
        import base64 as _b64

        b64 = _b64.b64encode(data).decode("ascii")
        message = [{"type": "file", "data": {"file": f"base64://{b64}", "name": name}}]
        return self._action(
            "send_private_msg", {"user_id": int(user_id), "message": message}
        )

    def send_group_file(self, group_id: str, file_path: str, name: str) -> OneBotSendResult:
        """Upload and send a file to a group."""
        return self._action(
            "upload_group_file",
            {"group_id": int(group_id), "file": file_path, "name": name},
        )

    def send_private_file(self, user_id: str, file_path: str, name: str) -> OneBotSendResult:
        """Upload and send a file to a private chat."""
        return self._action(
            "upload_private_file",
            {"user_id": int(user_id), "file": file_path, "name": name},
        )

    def get_file(self, file_id: str) -> dict[str, Any]:
        return self._action("get_file", {"file_id": file_id}).response

    # ------------------------------------------------------------------
    # ChannelClient ABC implementation
    # ------------------------------------------------------------------

    def send_message(
        self, conversation_id: str, text: str, reply_to: str | None = None
    ) -> Any:
        """Send a message via the unified ChannelClient interface."""
        if conversation_id.startswith("group:"):
            group_id = conversation_id.removeprefix("group:")
            return self.send_group_msg(group_id, text, reply_to=reply_to)
        elif conversation_id.startswith("private:"):
            user_id = conversation_id.removeprefix("private:")
            return self.send_private_msg(user_id, text)
        raise ValueError(f"Unknown conversation format: {conversation_id}")

    def send_file(
        self, conversation_id: str, data: bytes, filename: str
    ) -> Any:
        """Send a file via the unified ChannelClient interface."""
        if conversation_id.startswith("group:"):
            group_id = conversation_id.removeprefix("group:")
            return self.send_group_file_base64(group_id, data, filename)
        elif conversation_id.startswith("private:"):
            user_id = conversation_id.removeprefix("private:")
            return self.send_private_file_base64(user_id, data, filename)
        raise ValueError(f"Unknown conversation format: {conversation_id}")

    def _action(self, action: str, payload: dict[str, Any]) -> OneBotSendResult:
        headers = {}
        if self.access_token is not None:
            headers["authorization"] = f"Bearer {self.access_token.get_secret_value()}"
        response = self._client.post(f"{self.base_url}/{action}", json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict) and body.get("status") == "failed":
            raise OneBotClientError(str(body.get("wording") or body.get("msg") or body))
        if not isinstance(body, dict):
            raise OneBotClientError("OneBot response must be an object")
        return OneBotSendResult(action=action, payload=payload, response=body)
