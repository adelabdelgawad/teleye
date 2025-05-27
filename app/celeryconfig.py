from core.config import settings

broker_url = (settings.celery_broker_url,)
celery_result_backend = (settings.celery_result_backend,)

task_send_sent_event = False
