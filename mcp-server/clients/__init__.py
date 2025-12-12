"""
HTTP клиенты для подключения к серверам мониторинга
"""

from .prometheus_client import PrometheusClient
from .loki_client import LokiClient

__all__ = ["PrometheusClient", "LokiClient"]

