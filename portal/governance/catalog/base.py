"""Catalog adapter base class. All catalog backends (OpenMetadata, Alation, mock) implement this."""
from abc import ABC, abstractmethod
from typing import Any


class BaseCatalogClient(ABC):
    """Common interface so the pipeline can publish to any backend interchangeably."""
    provider: str = "base"

    @abstractmethod
    def publish_data_product(self, dp: dict) -> dict[str, Any]:
        """Publish a Data Product and return {'external_id': str, 'status': str, ...}."""

    def health(self) -> dict[str, Any]:
        return {"provider": self.provider, "status": "unknown"}
