"""Run the notification service: python -m notification_service"""

import logging
import os

import uvicorn

from notification_service import config

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs every request at INFO
uvicorn.run("notification_service.app:app", host=config.HOST, port=config.PORT)
