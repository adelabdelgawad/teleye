from celery import Celery
from core.config import settings

celery_worker = Celery(
    "teleye",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "tasks.channel_tasks",
        "tasks.message_tasks",
        "tasks.sync_tasks",
        "tasks.smart_sync_tasks",
        "tasks.listener_tasks",
    ],
)
celery_worker.conf.accept_content = ["pickle", "json", "msgpack", "yaml"]
celery_worker.conf.worker_send_task_events = True
