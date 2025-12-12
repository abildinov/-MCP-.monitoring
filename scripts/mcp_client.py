"""
MCP клиент для подключения Telegram бота к MCP серверу
"""

import httpx
import json
from typing import Dict, Any, Optional
from loguru import logger


class MCPClient:
    """Клиент для подключения к MCP серверу через HTTP/SSE"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Инициализация MCP клиента
        
        Args:
            base_url: URL MCP сервера
        """
        self.base_url = base_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=30.0)
        logger.info(f"MCP клиент инициализирован для {self.base_url}")
    
    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """
        Вызов MCP tool
        
        Args:
            tool_name: Название tool
            arguments: Аргументы для tool
            
        Returns:
            Результат выполнения tool
        """
        try:
            # Формируем запрос
            payload = {
                "name": tool_name,
                "arguments": arguments or {}
            }
            
            logger.info(f"Вызов MCP tool: {tool_name} с аргументами: {arguments}")
            
            # Отправляем запрос
            response = await self.client.post(
                f"{self.base_url}/call_tool",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            
            # Парсим ответ
            result = response.json()
            
            # Извлекаем текст из ответа
            if "content" in result and len(result["content"]) > 0:
                text_content = result["content"][0].get("text", "")
                logger.info(f"MCP tool {tool_name} выполнен успешно")
                return text_content
            else:
                logger.warning(f"MCP tool {tool_name} вернул пустой ответ")
                return "Пустой ответ от MCP tool"
                
        except httpx.HTTPError as e:
            error_msg = str(e)
            logger.error(f"HTTP ошибка при вызове MCP tool {tool_name}: {error_msg}")
            
            # Более информативное сообщение об ошибке
            if "connection" in error_msg.lower():
                return f"MCP сервер недоступен на {self.base_url}"
            elif "timeout" in error_msg.lower():
                return f"Timeout: MCP сервер не ответил"
            else:
                return f"Ошибка HTTP: {error_msg}"
        except Exception as e:
            logger.error(f"Ошибка при вызове MCP tool {tool_name}: {e}")
            return f"Ошибка: {str(e)}"
    
    async def get_tools(self) -> Dict[str, Any]:
        """
        Получить список доступных tools
        
        Returns:
            Словарь с информацией о tools
        """
        try:
            response = await self.client.get(f"{self.base_url}/tools")
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Получен список tools: {len(result.get('tools', []))} инструментов")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка получения списка tools: {e}")
            return {"tools": []}
    
    async def health_check(self) -> bool:
        """
        Проверка здоровья MCP сервера
        
        Returns:
            True если сервер доступен
        """
        try:
            response = await self.client.get(f"{self.base_url}/health", timeout=5.0)
            is_healthy = response.status_code == 200
            
            if is_healthy:
                logger.info("MCP сервер: здоров ✓")
            else:
                logger.warning(f"MCP сервер: нездоров (status {response.status_code})")
            
            return is_healthy
            
        except httpx.ConnectError as e:
            logger.error(f"❌ MCP сервер недоступен на {self.base_url}")
            logger.error(f"   Ошибка подключения: {e}")
            logger.error("   ⚠️  Убедитесь, что 'python server.py --transport http' запущен!")
            return False
        except Exception as e:
            logger.error(f"❌ MCP сервер недоступен: {e}")
            logger.exception("Полный traceback:")
            return False
    
    async def get_resources(self) -> Dict[str, Any]:
        """
        Получить список доступных Resources
        
        Returns:
            Словарь с информацией о resources
        """
        try:
            response = await self.client.get(f"{self.base_url}/resources")
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Получен список resources: {len(result.get('resources', []))} ресурсов")
            return result
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP ошибка получения списка resources: {e}")
            logger.exception("Полный traceback:")
            return {"resources": []}
        except Exception as e:
            logger.error(f"Ошибка получения списка resources: {e}")
            logger.exception("Полный traceback:")
            return {"resources": []}
    
    async def read_resource(self, uri: str) -> str:
        """
        Прочитать Resource по URI
        
        Args:
            uri: URI ресурса (например "metrics/cpu/current" или "monitoring://metrics/cpu/current")
            
        Returns:
            Содержимое ресурса (обычно JSON строка)
        """
        try:
            # Удаляем monitoring:// если есть (API сам добавит)
            clean_uri = uri.replace("monitoring://", "")
            
            logger.info(f"Чтение resource: {clean_uri}")
            
            response = await self.client.get(f"{self.base_url}/resource/{clean_uri}")
            response.raise_for_status()
            
            result = response.json()
            content = result.get("content", "")
            
            logger.info(f"Resource {clean_uri} прочитан успешно")
            return content
            
        except httpx.HTTPError as e:
            error_msg = str(e)
            logger.error(f"HTTP ошибка при чтении resource {uri}: {error_msg}")
            return f"Ошибка чтения resource: {error_msg}"
        except Exception as e:
            logger.error(f"Ошибка при чтении resource {uri}: {e}")
            return f"Ошибка: {str(e)}"
    
    async def get_prompts(self) -> Dict[str, Any]:
        """
        Получить список доступных Prompts
        
        Returns:
            Словарь с информацией о prompts
        """
        try:
            response = await self.client.get(f"{self.base_url}/prompts")
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Получен список prompts: {len(result.get('prompts', []))} промптов")
            return result
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP ошибка получения списка prompts: {e}")
            logger.exception("Полный traceback:")
            return {"prompts": []}
        except Exception as e:
            logger.error(f"Ошибка получения списка prompts: {e}")
            logger.exception("Полный traceback:")
            return {"prompts": []}
    
    async def generate_prompt(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """
        Сгенерировать Prompt с актуальными данными
        
        Args:
            name: Имя промпта (например "analyze_server_health")
            arguments: Аргументы для промпта (например {"detail_level": "detailed"})
            
        Returns:
            Сгенерированный текст промпта с метриками
        """
        try:
            payload = {"arguments": arguments or {}}
            
            logger.info(f"Генерация prompt: {name} с аргументами: {arguments}")
            
            response = await self.client.post(
                f"{self.base_url}/prompt/{name}",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            
            result = response.json()
            content = result.get("content", "")
            
            # Извлекаем текст из TextContent объекта
            if isinstance(content, dict) and "text" in content:
                text = content["text"]
            elif isinstance(content, str):
                text = content
            else:
                text = str(content)
            
            logger.info(f"Prompt {name} сгенерирован успешно")
            return text
            
        except httpx.HTTPError as e:
            error_msg = str(e)
            logger.error(f"HTTP ошибка при генерации prompt {name}: {error_msg}")
            return f"Ошибка генерации prompt: {error_msg}"
        except Exception as e:
            logger.error(f"Ошибка при генерации prompt {name}: {e}")
            return f"Ошибка: {str(e)}"
    
    async def close(self):
        """Закрыть соединения"""
        await self.client.aclose()
        logger.info("MCP клиент закрыт")


# Пример использования
if __name__ == "__main__":
    import asyncio
    
    async def test():
        client = MCPClient()
        
        # Проверка здоровья
        is_healthy = await client.health_check()
        print(f"MCP сервер здоров: {is_healthy}")
        
        if is_healthy:
            # Получение списка tools
            tools = await client.get_tools()
            print(f"Доступные tools: {tools}")
            
            # Тест вызова tool
            result = await client.call_tool("get_cpu_usage")
            print(f"Результат get_cpu_usage: {result}")
        
        await client.close()
    
    asyncio.run(test())
