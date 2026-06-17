"""Catalog factory: returns a configured client based on CATALOG_PROVIDER."""
import logging

from django.conf import settings

from .base import BaseCatalogClient
from .mock import MockCatalogClient
from .openmetadata import OpenMetadataClient, OpenMetadataError
from .alation import AlationClient, AlationError

logger = logging.getLogger(__name__)

__all__ = ["BaseCatalogClient", "MockCatalogClient", "OpenMetadataClient", "AlationClient",
           "OpenMetadataError", "AlationError", "get_catalog_client"]


def get_catalog_client() -> BaseCatalogClient:
    """Return the configured catalog client.

    Resolution order:
      1. settings.CATALOG_PROVIDER == "openmetadata" + JWT present -> OpenMetadata
      2. settings.CATALOG_PROVIDER == "alation" and ALATION_MODE=="real" -> Alation
      3. otherwise -> Mock (writes payloads to ./alation_sync/)
    """
    provider = (settings.CATALOG_PROVIDER or "mock").lower()

    if provider == "openmetadata":
        if not settings.OPENMETADATA.get("JWT_TOKEN"):
            logger.warning("OPENMETADATA_JWT_TOKEN not set -> falling back to MOCK adapter. "
                           "Paste a bot token into .env to publish to OpenMetadata UI.")
            return MockCatalogClient()
        return OpenMetadataClient()

    if provider == "alation":
        if settings.ALATION.get("MODE") != "real" or not settings.ALATION.get("BASE_URL"):
            logger.warning("ALATION_MODE != 'real' or missing credentials -> using MOCK adapter.")
            return MockCatalogClient()
        return AlationClient()

    return MockCatalogClient()
