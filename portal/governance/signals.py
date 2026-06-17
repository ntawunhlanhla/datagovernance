"""Django signals: when a DataProductUpload is saved, trigger the ingestion pipeline."""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import DataProductUpload

logger = logging.getLogger(__name__)


@receiver(post_save, sender=DataProductUpload)
def trigger_ingestion(sender, instance: DataProductUpload, created: bool, **kwargs):
    # Only trigger on initial upload
    if not created:
        return
    from .tasks import ingest_data_product_excel
    logger.info("DataProductUpload #%s created, dispatching ingestion task", instance.pk)
    ingest_data_product_excel.delay(instance.pk)
