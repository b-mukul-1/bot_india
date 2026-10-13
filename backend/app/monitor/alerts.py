"""
APEX-IN Alert Notification Dispatcher
Sends high-priority operational alerts to Telegram / Discord webhooks.
Notifies owner on:
1. 401/403 API key expiration
2. Emergency Kill Switch triggers
3. Daily loss breaches
4. Reconciliation mismatches
"""

import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

class AlertManager:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url

    def send_alert(self, title: str, message: str, level: str = "INFO") -> bool:
        logger.info(f"[ALERT {level}] {title}: {message}")
        if not self.webhook_url:
            return False

        payload = {
            "content": f"🚨 **APEX-IN [{level}]**: {title}\n{message}"
        }

        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.post(self.webhook_url, json=payload)
                return res.status_code < 400
        except Exception as e:
            logger.error(f"Failed to deliver alert webhook: {e}")
            return False
