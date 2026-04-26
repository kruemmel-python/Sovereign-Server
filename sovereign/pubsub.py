from __future__ import annotations

from .eventhub import EventHub, SSESession, WebSocketConnection, event_hub

class WSHub(EventHub):
    pass

wshub = event_hub
