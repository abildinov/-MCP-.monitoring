"""
Универсальный LLM клиент для работы с DeepSeek V3.1
"""
import os
from typing import Dict, Any
from .deepseek_client import DeepSeekClient
from loguru import logger


class UniversalLLMClient:
    """Универсальный клиент для работы с DeepSeek V3.1"""
    
    def __init__(self):
        self.provider = "deepseek"
        self.client = DeepSeekClient()
    
    async def analyze_metrics(self, metrics_data: Dict[str, Any], context: str = "") -> str:
        """Анализ метрик через DeepSeek V3.1"""
        try:
            logger.info(f"Анализ метрик через {self.provider}")
            return await self.client.analyze_metrics(metrics_data, context)
        except Exception as e:
            logger.error(f"Ошибка анализа через {self.provider}: {e}")
            return f"Ошибка анализа: {str(e)}"
    
    async def generate_report_analysis(self, data: Dict[str, Any], period: str) -> str:
        """Генерация полного анализа для отчёта через DeepSeek V3.1"""
        try:
            logger.info(f"Генерация анализа отчёта через {self.provider} за период {period}")
            return await self.client.generate_report_analysis(data, period)
        except Exception as e:
            logger.error(f"Ошибка генерации анализа отчёта через {self.provider}: {e}")
            return f"Ошибка генерации анализа отчёта: {str(e)}"
    
    async def check_health(self) -> bool:
        """Проверка доступности LLM клиента"""
        try:
            # Простая проверка - если клиент создан, значит он доступен
            return self.client is not None
        except Exception as e:
            logger.error(f"Ошибка проверки здоровья LLM: {e}")
            return False
    
    async def close(self):
        """Закрытие клиента"""
        try:
            if hasattr(self.client, 'close'):
                await self.client.close()
        except Exception as e:
            logger.error(f"Ошибка закрытия LLM клиента: {e}")
    
    @property
    def provider_name(self) -> str:
        """Название текущего провайдера"""
        return self.provider