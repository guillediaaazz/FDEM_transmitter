from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from ..events import TransportEvent, TransportKind

EventSink = Callable[[TransportEvent], None]


class Transport(ABC):
    kind: TransportKind

    def __init__(self, event_sink: EventSink) -> None:
        self.event_sink = event_sink

    @property
    @abstractmethod
    def connected(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def send_line(self, line: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    def shutdown(self) -> None:
        self.disconnect()

