"""A scripted chat client for exercising the real Agent Framework loop without a model.

``ScriptedClient(responder)`` calls ``responder(agent_name, messages)`` for each model turn;
the responder returns either a str (assistant text) or a dict ``{"call": name, "args": {...}}``
(a function call that Agent Framework will execute against the agent's tools).
"""

from __future__ import annotations

import json
from itertools import count

from agent_framework import BaseChatClient, ChatResponse, Content, FunctionInvocationLayer, Message


class ScriptedClient(FunctionInvocationLayer, BaseChatClient):
    def __init__(self, responder) -> None:
        super().__init__()
        self.responder = responder
        self.turns: list[tuple[str, int]] = []
        self._ids = count(1)

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        agent = "Analyst" if (options or {}).get("tools") else "Narrator"
        self.turns.append((agent, len(messages)))
        out = self.responder(agent, messages)
        if isinstance(out, dict):
            content = Content.from_function_call(call_id=f"c{next(self._ids)}", name=out["call"], arguments=json.dumps(out.get("args", {})))
        else:
            content = out

        async def respond():
            return ChatResponse(messages=[Message(role="assistant", contents=[content])])

        return respond()


def message_texts(messages) -> list[str]:
    out = []
    for m in messages:
        for c in m.contents:
            text = getattr(c, "text", None)
            if text:
                out.append(text)
            result = getattr(c, "result", None)
            if result is not None:
                out.append(str(result))
    return out
