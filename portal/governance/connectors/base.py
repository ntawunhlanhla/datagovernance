"""Base class for source connectors. All connectors implement the same minimal interface
so the portal can swap between MinIO, S3, Athena, Glue, Marquez, ... without code changes."""
from abc import ABC, abstractmethod
from importlib import import_module
from typing import Any

from django.conf import settings


class BaseConnector(ABC):
    kind: str = "base"

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    def discover_datasets(self, prefix: str = "") -> list[dict]:
        """Return [{name, path, format, ...}, ...] of datasets visible to this connector."""

    @abstractmethod
    def read_schema(self, dataset_name: str) -> list[dict]:
        """Return [{name, data_type, nullable, ...}, ...] for the dataset."""

    @abstractmethod
    def read_sample(self, dataset_name: str, n: int = 10) -> list[dict]:
        """Return up to n sample rows."""

    def health(self) -> dict[str, Any]:
        return {"kind": self.kind, "status": "unknown"}


def get_connector(kind: str, config: dict | None = None) -> BaseConnector:
    """Instantiate a connector by kind, using settings.CONNECTORS for the dotted path."""
    dotted = settings.CONNECTORS.get(kind)
    if not dotted:
        raise ValueError(f"Unknown connector kind: {kind}")
    module_path, class_name = dotted.rsplit(".", 1)
    cls = getattr(import_module(module_path), class_name)
    return cls(config=config)
