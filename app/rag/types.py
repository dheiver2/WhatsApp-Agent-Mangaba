from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Document:
    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StoredChunk:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_document(self) -> Document:
        return Document(page_content=self.text, metadata=dict(self.metadata))
