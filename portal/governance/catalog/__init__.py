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
      1. settings.CATALOG_PROVIDER == "openmetadata" -> OpenMetadata
         (JWT auto-bootstraps from admin creds if not explicitly set; falls back to mock on failure)
      2. settings.CATALOG_PROVIDER == "alation" and ALATION_MODE == "real" -> Alation
      3. otherwise -> Mock (writes payloads to ./alation_sync/)
    """
    provider = (settings.CATALOG_PROVIDER or "mock").lower()

    if provider == "openmetadata":
        try:
            return OpenMetadataClient()
        except OpenMetadataError as e:
            logger.warning("OpenMetadata adapter unavailable (%s) -> falling back to MOCK.", e)
            return MockCatalogClient()

    if provider == "alation":
        if settings.ALATION.get("MODE") != "real" or not settings.ALATION.get("BASE_URL"):
            logger.warning("ALATION_MODE != 'real' or missing credentials -> using MOCK adapter.")
            return MockCatalogClient()
        return AlationClient()

    return MockCatalogClient()
