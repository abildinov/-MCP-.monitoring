"""
HTTP клиент для Loki
Получает логи с удаленного сервера
"""

import httpx
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from loguru import logger


class LokiClient:
    """HTTP клиент для удаленного Loki"""
    
    def __init__(self, base_url: str, timeout: int = 30):
        """
        Инициализация клиента
        
        Args:
            base_url: URL Loki сервера (например, http://147.45.157.2:3100)
            timeout: Таймаут запросов в секундах
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        logger.info(f"LokiClient инициализирован: {self.base_url}")
    
    async def query_range(
        self,
        logql: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
        direction: str = "backward"
    ) -> Dict[str, Any]:
        """
        Запрос логов за период
        
        Args:
            logql: LogQL выражение
            start: Начало периода
            end: Конец периода
            limit: Максимальное количество строк
            direction: Направление (backward/forward)
            
        Returns:
            Результат запроса с логами
        """
        url = f"{self.base_url}/loki/api/v1/query_range"
        params = {
            "query": logql,
            "start": int(start.timestamp() * 1e9),  # nanoseconds
            "end": int(end.timestamp() * 1e9),
            "limit": limit,
            "direction": direction
        }
        
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "success":
                logger.error(f"Loki query error: {data}")
                return {"status": "error", "data": {}}
            
            logger.debug(f"Loki query успешен: {logql[:50]}...")
            return data
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP ошибка при запросе к Loki: {e}")
            return {"status": "error", "error": str(e), "data": {}}
    
    async def search_logs(
        self, 
        search_text: str, 
        hours: int = 1,
        limit: int = 50
    ) -> List[str]:
        """
        Поиск по логам
        
        Args:
            search_text: Текст для поиска
            hours: Сколько часов назад искать
            limit: Максимум строк
            
        Returns:
            Список найденных строк логов
        """
        end = datetime.now()
        start = end - timedelta(hours=hours)
        
        # LogQL запрос с поиском
        logql = f'{{job="varlogs"}} |= "{search_text}"'
        
        result = await self.query_range(logql, start, end, limit=limit)
        
        logs = []
        if result.get("status") == "success" and result["data"].get("result"):
            for stream in result["data"]["result"]:
                for entry in stream.get("values", []):
                    timestamp_ns, log_line = entry
                    logs.append(log_line)
            
            logger.info(f"Найдено {len(logs)} строк логов с '{search_text}'")
        
        return logs
    
    async def get_error_logs(
        self, 
        hours: int = 1,
        limit: int = 50
    ) -> List[Dict[str, str]]:
        """
        Получить логи с ошибками
        
        Args:
            hours: Сколько часов назад
            limit: Максимум строк
            
        Returns:
            Список ошибок с timestamp и текстом
        """
        end = datetime.now()
        start = end - timedelta(hours=hours)
        
        # Поиск ошибок (case-insensitive)
        logql = '{job="varlogs"} |~ "(?i)(error|exception|fail|critical)"'
        
        result = await self.query_range(logql, start, end, limit=limit)
        
        errors = []
        if result.get("status") == "success" and result["data"].get("result"):
            for stream in result["data"]["result"]:
                container = stream.get("stream", {}).get("container_name", "unknown")
                
                for entry in stream.get("values", []):
                    timestamp_ns, log_line = entry
                    # Конвертация nanoseconds в datetime
                    dt = datetime.fromtimestamp(int(timestamp_ns) / 1e9)
                    
                    errors.append({
                        "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "container": container,
                        "message": log_line
                    })
            
            logger.info(f"Найдено {len(errors)} ошибок за последние {hours}ч")
        
        return errors
    
    async def get_logs_by_container(
        self,
        container_name: str,
        hours: int = 1,
        limit: int = 50
    ) -> List[str]:
        """
        Получить логи конкретного контейнера
        
        Args:
            container_name: Имя контейнера
            hours: Период
            limit: Максимум строк
            
        Returns:
            Список логов
        """
        end = datetime.now()
        start = end - timedelta(hours=hours)
        
        logql = f'{{container_name="{container_name}"}}'
        
        result = await self.query_range(logql, start, end, limit=limit)
        
        logs = []
        if result.get("status") == "success" and result["data"].get("result"):
            for stream in result["data"]["result"]:
                for entry in stream.get("values", []):
                    timestamp_ns, log_line = entry
                    logs.append(log_line)
            
            logger.info(f"Получено {len(logs)} логов от {container_name}")
        
        return logs
    
    async def get_log_labels(self) -> Optional[List[str]]:
        """
        Получить доступные labels в Loki
        
        Returns:
            Список labels
        """
        url = f"{self.base_url}/loki/api/v1/labels"
        
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") == "success":
                labels = data.get("data", [])
                logger.info(f"Доступные labels: {labels}")
                return labels
            
        except httpx.HTTPError as e:
            logger.error(f"Ошибка получения labels: {e}")
        
        return None
    
    async def get_label_values(self, label: str) -> Optional[List[str]]:
        """
        Получить значения для конкретного label
        
        Args:
            label: Имя label (например, "container_name")
            
        Returns:
            Список значений
        """
        url = f"{self.base_url}/loki/api/v1/label/{label}/values"
        
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") == "success":
                values = data.get("data", [])
                logger.info(f"Значения для {label}: {values}")
                return values
            
        except httpx.HTTPError as e:
            logger.error(f"Ошибка получения values для {label}: {e}")
        
        return None
    
    async def check_health(self) -> bool:
        """
        Проверка доступности Loki
        
        Returns:
            True если Loki доступен
        """
        try:
            url = f"{self.base_url}/ready"
            response = await self.client.get(url, timeout=5)
            is_healthy = response.status_code == 200
            
            if is_healthy:
                logger.info("Loki: готов ✓")
            else:
                logger.warning(f"Loki: не готов (status {response.status_code})")
            
            return is_healthy
            
        except Exception as e:
            logger.error(f"Loki недоступен: {e}")
            return False
    
    async def close(self):
        """Закрыть соединения"""
        await self.client.aclose()
        logger.info("LokiClient закрыт")


# Пример использования
if __name__ == "__main__":
    import asyncio
    
    async def test():
        client = LokiClient("http://147.45.157.2:3100")
        
        # Проверка здоровья
        is_healthy = await client.check_health()
        print(f"Loki healthy: {is_healthy}")
        
        # Labels
        labels = await client.get_log_labels()
        print(f"Labels: {labels}")
        
        # Поиск ошибок
        errors = await client.get_error_logs(hours=24, limit=10)
        print(f"\nОшибки ({len(errors)}):")
        for err in errors[:3]:
            print(f"  [{err['timestamp']}] {err['container']}: {err['message'][:80]}...")
        
        await client.close()
    
    asyncio.run(test())

