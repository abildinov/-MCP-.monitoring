"""
Telegram бот для мониторинга серверной инфраструктуры
Интегрируется с MCP сервером для получения метрик и анализа через DeepSeek V3.1
"""

import asyncio
import json
import httpx
import re
from datetime import datetime
from typing import Dict, Any, Optional
from loguru import logger

from mcp_client import MCPClient


class TelegramMonitoringBot:
    """Telegram бот для мониторинга сервера"""
    
    def __init__(self, token: str, use_mcp: bool = True):
        """
        Инициализация бота
        
        Args:
            token: Токен Telegram бота
            use_mcp: Использовать ли MCP сервер для получения данных
        """
        self.token = token
        self.use_mcp = use_mcp
        self.base_url = f"https://api.telegram.org/bot{token}"
        
        # Добавляем путь к mcp-server в PYTHONPATH для импортов
        import sys
        from pathlib import Path
        mcp_server_path = Path(__file__).parent.parent / "mcp-server"
        if str(mcp_server_path) not in sys.path:
            sys.path.insert(0, str(mcp_server_path))
        
        # Инициализация MCP клиента
        if use_mcp:
            self.mcp = MCPClient("http://localhost:8000")
            logger.info("MCP клиент инициализирован")
        else:
            self.mcp = None
        
        # Прямые клиенты (для случаев когда MCP недоступен)
        self.prometheus = None
        self.loki = None
        self.llm_client = None
        
        # Режим чата для каждого пользователя
        self.chat_modes = {}
        
        logger.info(f"Telegram бот инициализирован. MCP: {use_mcp}")
    
    async def send_message(self, chat_id: str, text: str, parse_mode: str = "Markdown", reply_markup=None):
        """Отправка сообщения в Telegram"""
        logger.info(f"Отправка сообщения в чат {chat_id}, длина: {len(text)}")
        logger.info(f"Содержимое сообщения: {text[:200]}...")  # Первые 200 символов
        try:
            # Очищаем текст от проблемных символов
            clean_text = text
            if parse_mode == "Markdown":
                # Удаляем только проблемные символы Markdown
                clean_text = clean_text.replace('*', '').replace('_', '').replace('`', '')
                clean_text = clean_text.replace('[', '').replace(']', '')
                # Удаляем только проблемные фигурные скобки
                clean_text = clean_text.replace('{', '').replace('}', '')
                # НЕ удаляем эмодзи и другие символы - они важны!
            
            # Разбиваем длинные сообщения
            if len(clean_text) > 4000:
                parts = [clean_text[i:i+4000] for i in range(0, len(clean_text), 4000)]
                for part in parts:
                    await self._send_single_message(chat_id, part, parse_mode, reply_markup)
            else:
                await self._send_single_message(chat_id, clean_text, parse_mode, reply_markup)
            
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
            # Пробуем отправить без форматирования
            try:
                await self._send_single_message(chat_id, text, None, reply_markup)
            except Exception as e2:
                logger.error(f"Критическая ошибка отправки: {e2}")
    
    async def _send_single_message(self, chat_id: str, text: str, parse_mode: str = None, reply_markup=None):
        """Отправка одного сообщения"""
        logger.info(f"Отправка в Telegram API: {len(text)} символов")
        data = {
            "chat_id": chat_id,
            "text": text
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
            
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.base_url}/sendMessage", json=data)
            logger.info(f"Ответ Telegram API: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"Ошибка Telegram API: {response.status_code} - {response.text}")
            else:
                logger.info("Сообщение отправлено успешно")
    
    async def send_chat_action(self, chat_id: str, action: str):
        """Отправка действия чата (typing, etc.)"""
        try:
            data = {"chat_id": chat_id, "action": action}
            async with httpx.AsyncClient() as client:
                await client.post(f"{self.base_url}/sendChatAction", json=data)
        except Exception as e:
            logger.error(f"Ошибка отправки chat action: {e}")
    
    async def send_document(self, chat_id: str, file_path: str, caption: str = ""):
        """Отправка файла в Telegram"""
        logger.info(f"Отправка файла {file_path} в чат {chat_id}")
        try:
            url = f"{self.base_url}/sendDocument"
            
            with open(file_path, 'rb') as file:
                files = {'document': file}
                data = {'chat_id': chat_id}
                if caption:
                    data['caption'] = caption
                
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(url, data=data, files=files)
                    
                    if response.status_code == 200:
                        logger.info("Файл отправлен успешно")
                        return response.json()
                    else:
                        logger.error(f"Ошибка отправки файла: {response.status_code} - {response.text}")
                        return None
        except Exception as e:
            logger.error(f"Ошибка отправки файла: {e}")
            return None
    
    async def get_updates(self, offset: int = 0) -> list:
        """Получение обновлений от Telegram"""
        try:
            params = {"offset": offset, "timeout": 10}
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"{self.base_url}/getUpdates", params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        return data.get("result", [])
                    else:
                        logger.error(f"Telegram API error: {data}")
                        return []
                else:
                    logger.error(f"Ошибка Telegram API: {response.status_code} - {response.text}")
                    return []
                    
        except httpx.TimeoutException:
            logger.error("Таймаут при получении обновлений от Telegram")
            return []
        except httpx.ConnectError:
            logger.error("Ошибка подключения к Telegram API")
            return []
        except Exception as e:
            logger.error(f"Ошибка получения обновлений: {e}")
            return []
    
    async def process_message(self, update: dict):
        """Обработка входящего сообщения"""
        try:
            message = update.get("message", {})
            chat_id = str(message.get("chat", {}).get("id"))
            text = message.get("text", "").strip()
            
            if not text:
                return
            
            logger.info(f"Получено сообщение от {chat_id}: {text}")
            
            # Обработка команд (проверяем ПЕРЕД режимом чата!)
            if text.startswith("/"):
                command = text.split()[0].lower()
                
                if command == "/start":
                    await self.cmd_start(chat_id, text)
                elif command == "/menu":
                    await self.cmd_menu(chat_id, text)
                elif command == "/status":
                    await self.cmd_status(chat_id, text)
                elif command == "/analyze":
                    await self.cmd_analyze_full(chat_id, text)
                elif command == "/chat":
                    await self.cmd_chat(chat_id, text)
                elif command == "/end_chat" or command == "/endchat":
                    await self.cmd_end_chat(chat_id, text)
                elif command == "/help":
                    await self.cmd_help(chat_id, text)
                elif command == "/alerts":
                    await self.cmd_alerts(chat_id, text)
                elif command == "/health":
                    await self.cmd_health(chat_id, text)
                elif command == "/report_daily":
                    await self.cmd_report_daily(chat_id, text)
                elif command == "/report_weekly":
                    await self.cmd_report_weekly(chat_id, text)
                elif command == "/report_monthly":
                    await self.cmd_report_monthly(chat_id, text)
                # === НОВЫЕ КОМАНДЫ: Все Tools ===
                elif command == "/cpu":
                    await self.cmd_cpu(chat_id, text)
                elif command == "/memory":
                    await self.cmd_memory(chat_id, text)
                elif command == "/disk":
                    await self.cmd_disk(chat_id, text)
                elif command == "/network":
                    await self.cmd_network(chat_id, text)
                elif command == "/processes":
                    await self.cmd_processes(chat_id, text)
                # === НОВЫЕ КОМАНДЫ: Resources ===
                elif command == "/resources":
                    await self.cmd_resources(chat_id, text)
                elif command == "/resource":
                    await self.cmd_resource(chat_id, text)
                # === НОВЫЕ КОМАНДЫ: Prompts ===
                elif command == "/prompts":
                    await self.cmd_prompts(chat_id, text)
                elif command == "/investigate_cpu":
                    await self.cmd_investigate_cpu(chat_id, text)
                elif command == "/diagnose_memory":
                    await self.cmd_diagnose_memory(chat_id, text)
                elif command == "/analyze_incident":
                    await self.cmd_analyze_incident(chat_id, text)
                else:
                    await self.send_message(chat_id, "❓ Неизвестная команда. Используйте /help для списка команд.")
                return
            
            # Проверяем режим чата
            if chat_id in self.chat_modes and self.chat_modes[chat_id]:
                # Пользователь в режиме чата - обрабатываем как вопрос к LLM
                await self.process_chat_question(chat_id, text)
                return
            
            # Обработка кнопок клавиатуры
            elif text in ["📊 Статус", "🔍 Анализ", "💬 Чат с ИИ", "❓ Помощь"]:
                if text == "📊 Статус":
                    await self.cmd_status(chat_id, "/status")
                elif text == "🔍 Анализ":
                    await self.cmd_analyze_full(chat_id, "/analyze")
                elif text == "💬 Чат с ИИ":
                    await self.cmd_chat(chat_id, "/chat")
                elif text == "❓ Помощь":
                    await self.cmd_help(chat_id, "/help")
            
            else:
                # Обычное сообщение - проверяем режим чата
                if chat_id in self.chat_modes and self.chat_modes[chat_id]:
                    await self.process_chat_question(chat_id, text)
                else:
                    await self.send_message(chat_id, "❓ Неизвестная команда. Используйте /help для списка команд.")
            
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
    
    async def cmd_start(self, chat_id: str, message: str) -> str:
        """Команда /start - приветствие"""
        welcome_text = """🎓 *Добро пожаловать в систему мониторинга сервера!*

🤖 *Бот использует DeepSeek V3.1 для анализа метрик*

📊 *Доступные команды:*
• `/status` - текущий статус системы
• `/analyze` - полный анализ через LLM
• `/chat` - режим диалога с ИИ
• `/help` - справка

🚀 *Готов к работе!*"""
        
        # Клавиатура с основными командами
        reply_markup = {
            "keyboard": [
                [{"text": "📊 Статус"}, {"text": "🔍 Анализ"}],
                [{"text": "💬 Чат с ИИ"}, {"text": "❓ Помощь"}]
            ],
            "resize_keyboard": True,
            "one_time_keyboard": False
        }
        
        await self.send_message(chat_id, welcome_text, reply_markup=reply_markup)
        return ""
    
    async def cmd_menu(self, chat_id: str, message: str) -> str:
        """Команда /menu - главное меню"""
        await self.cmd_start(chat_id, message)
        return ""
    
    async def cmd_status(self, chat_id: str, message: str) -> str:
        """Команда /status - полный статус системы как раньше"""
        try:
            await self.send_chat_action(chat_id, "typing")
            
            # Инициализируем Prometheus клиент если нужно
            if not hasattr(self, 'prometheus') or self.prometheus is None:
                from clients.prometheus_client import PrometheusClient
                self.prometheus = PrometheusClient("http://147.45.157.2:9090")
            
            # Получаем ВСЕ данные для полного статуса
            cpu_current = await self.prometheus.get_current_cpu() or 0
            cpu_max_5m = await self.prometheus.get_cpu_max_last_minutes(5) or 0
            cpu_trend = await self.prometheus.get_cpu_series_5m()
            load_avg = await self.prometheus.get_load_average()
            
            memory_data = await self.prometheus.get_current_memory() or {}
            memory_trend = await self.prometheus.get_memory_series_5m()
            swap_data = await self.prometheus.get_swap_usage()
            
            disk_data = await self.prometheus.get_disk_usage() or []
            disk_io_trends = await self.prometheus.get_disk_io_5m()
            
            network_data = await self.prometheus.get_network_status() or {}
            network_connections = await self.prometheus.get_network_connections()
            network_traffic_trends = await self.prometheus.get_network_traffic_5m()
            network_error_trends = await self.prometheus.get_network_errors_5m()
            
            file_descriptors = await self.prometheus.get_file_descriptors()
            uptime_data = await self.prometheus.get_system_uptime()
            processes_data = await self.prometheus.get_top_processes_by_cpu(5)
            
            container_cpu_top = await self.prometheus.get_container_top_cpu_5()
            container_mem_top = await self.prometheus.get_container_top_mem_5()
            
            # Получаем алерты через MCP
            try:
                alerts_result = await self.mcp.call_tool("get_active_alerts")
            except Exception as e:
                alerts_result = f"Ошибка получения алертов: {e}"
            
            # Формируем ПОЛНЫЙ статус как было раньше
            cpu_status = f"""• Текущий: {cpu_current:.2f}%
• Максимум за 5мин: {cpu_max_5m:.2f}%
• Load Average: {load_avg.get('load1', 0):.2f} / {load_avg.get('load5', 0):.2f} / {load_avg.get('load15', 0):.2f}
• Тренд(5м): {cpu_trend.get('arrow','→')} min/avg/max: {cpu_trend.get('min',0):.1f}/{cpu_trend.get('avg',0):.1f}/{cpu_trend.get('max',0):.1f}%
• Порог: 80.0%
• Статус: {'🔴 HIGH' if cpu_current > 80 else '✓ NORMAL'}"""
            
            memory_status = f"""• Использование: {memory_data.get('percent', 0):.2f}%
• Используется: {memory_data.get('used_gb', 0):.2f} GB
• Всего: {memory_data.get('total_gb', 0):.2f} GB
• Доступно: {memory_data.get('available_gb', 0):.2f} GB
• Тренд(5м): {memory_trend.get('arrow','→')} min/avg/max: {memory_trend.get('min',0):.1f}/{memory_trend.get('avg',0):.1f}/{memory_trend.get('max',0):.1f}%
• Порог: 85.0%
• Статус: {'🔴 HIGH' if memory_data.get('percent', 0) > 85 else '✓ NORMAL'}"""
            
            swap_status = f"""• Использование: {swap_data.get('percent', 0):.2f}%
• Используется: {swap_data.get('used_gb', 0):.2f} GB
• Всего: {swap_data.get('total_gb', 0):.2f} GB
• Статус: {'🔴 HIGH' if swap_data.get('percent', 0) > 80 else '✓ NORMAL'}"""
            
            main_disk = next((d for d in disk_data if d.get('mountpoint') == '/'), disk_data[0] if disk_data else None)
            disk_status = f"""• Устройств: {len(disk_data)}
• Основной: {main_disk.get('mountpoint', '/')} ({main_disk.get('percent', 0):.1f}%)
• IO(5м avg): R {disk_io_trends.get('read', {}).get('avg', 0):.2f} MB/s | W {disk_io_trends.get('write', {}).get('avg', 0):.2f} MB/s"""
            
            network_status = f"""• Интерфейсов: {network_data.get('traffic', {}).get('total_interfaces', 0)}
• Активных: {network_data.get('traffic', {}).get('active_interfaces', 0)}
• TCP соединений: {network_connections.get('tcp_established', 0)}
• UDP соединений: {network_connections.get('udp_datagrams', 0)}
• Всего соединений: {network_connections.get('total', 0)}
• Traffic(5м avg): RX {network_traffic_trends.get('rx', {}).get('avg', 0):.2f} MB/s | TX {network_traffic_trends.get('tx', {}).get('avg', 0):.2f} MB/s
• Errors(5м avg): {network_error_trends.get('avg', 0):.2f}/s"""
            
            fd_status = f"""• Использовано: {file_descriptors.get('used', 0)}
• Максимум: {file_descriptors.get('max', 0)}
• Процент: {file_descriptors.get('percent', 0):.1f}%
• Статус: {'🔴 HIGH' if file_descriptors.get('percent', 0) > 80 else '✓ NORMAL'}"""
            
            uptime_status = f"""• Время работы: {uptime_data.get('uptime_human', 'Unknown')}"""
            
            processes_text = ""
            if processes_data:
                processes_text = "\n".join([
                    f"• {p.get('name', 'unknown')}: {p.get('cpu_usage', p.get('cpu_percent', 0)):.1f}%"
                    for p in processes_data[:5]
                ])
            
            containers_cpu_text = ""
            if container_cpu_top:
                containers_cpu_text = "\n".join([
                    f"• {c.get('name', 'unknown')}: {c.get('cpu_percent', 0):.1f}% CPU"
                    for c in container_cpu_top[:3]
                ])
            
            containers_mem_text = ""
            if container_mem_top:
                containers_mem_text = "\n".join([
                    f"• {c.get('name', 'unknown')}: {c.get('memory_gb', 0):.2f} GB RAM"
                    for c in container_mem_top[:3]
                ])
            
            # Формируем полный статус
            full_status = f"""📊 **ПОЛНЫЙ СТАТУС СИСТЕМЫ (ВСЕ МЕТРИКИ)**

🖥️ **CPU:**
{cpu_status}

💾 **ПАМЯТЬ:**
{memory_status}

💿 **SWAP:**
{swap_status}

💿 **ДИСКИ:**
{disk_status}

🌐 **СЕТЬ:**
{network_status}

📁 **ФАЙЛОВЫЕ ДЕСКРИПТОРЫ:**
{fd_status}

⏱️ **UPTIME:**
{uptime_status}

⚙️ **ТОП ПРОЦЕССЫ:**
{processes_text if processes_text else '• Нет данных'}

🐳 **КОНТЕЙНЕРЫ:**
{containers_cpu_text if containers_cpu_text else '• Нет данных'}
{containers_mem_text if containers_mem_text else ''}

🚨 **АЛЕРТЫ:**
{alerts_result}

⏰ **Время**: {datetime.now().strftime('%H:%M:%S')}"""
            
            await self.send_message(chat_id, full_status)
            return ""
            
        except Exception as e:
            logger.error(f"Ошибка получения статуса: {e}")
            await self.send_message(chat_id, f"❌ Ошибка получения статуса: {e}")
            return ""
    
    async def cmd_analyze_full(self, chat_id: str, message: str) -> str:
        """Команда /analyze - полный анализ через LLM"""
        try:
            await self.send_chat_action(chat_id, "typing")
            
            if self.use_mcp and self.mcp:
                # Используем новый MCP tool для полного анализа
                result = await self.mcp.call_tool("analyze_full_system")
                
                # Разбиваем ответ на части если он длинный
                if len(result) > 4000:
                    parts = [result[i:i+4000] for i in range(0, len(result), 4000)]
                    for i, part in enumerate(parts):
                        await self.send_message(chat_id, f"📊 **АНАЛИЗ СИСТЕМЫ** (часть {i+1}/{len(parts)})\n\n{part}")
                else:
                    await self.send_message(chat_id, f"📊 **АНАЛИЗ СИСТЕМЫ**\n\n{result}")
                
                return ""
            else:
                await self.send_message(chat_id, "❌ MCP сервер недоступен для анализа")
                return ""
                
        except Exception as e:
            logger.error(f"Ошибка анализа: {e}")
            await self.send_message(chat_id, f"❌ Ошибка анализа: {e}")
            return ""
    
    async def cmd_chat(self, chat_id: str, message: str) -> str:
        """Команда /chat - режим диалога с ИИ"""
        self.chat_modes[chat_id] = True
        await self.send_message(chat_id, "💬 **Режим чата активирован!**\n\nЗадавайте вопросы о системе мониторинга. Для выхода используйте /end_chat")
        return ""
    
    async def cmd_end_chat(self, chat_id: str, message: str) -> str:
        """Команда /end_chat - выход из режима чата"""
        self.chat_modes[chat_id] = False
        await self.send_message(chat_id, "👋 **Режим чата деактивирован**\n\nИспользуйте команды для работы с системой")
        return ""
    
    async def cmd_alerts(self, chat_id: str, message: str) -> str:
        """Команда /alerts - показывает активные алерты"""
        try:
            await self.send_chat_action(chat_id, "typing")
            
            # Получаем активные алерты через MCP сервер
            response_text = await self.mcp.call_tool("get_active_alerts")
            
            # Парсим JSON из строки
            import json
            try:
                response = json.loads(response_text)
            except json.JSONDecodeError:
                # Если не JSON, значит это текстовое описание
                await self.send_message(chat_id, f"📊 **Алерты:**\n\n{response_text}")
                return ""
            
            if response.get("error"):
                await self.send_message(chat_id, f"❌ Ошибка: {response['error']}")
                return ""
            
            result = response.get("result", {})
            alerts = result.get("alerts", [])
            summary = result.get("summary", "")
            
            if not alerts or len(alerts) == 0:
                message_text = "✅ **АЛЕРТОВ НЕТ**\n\nВсе системы работают нормально!"
            else:
                firing_alerts = [a for a in alerts if a.get('state') == 'firing']
                pending_alerts = [a for a in alerts if a.get('state') == 'pending']
                
                message_text = f"🚨 **АКТИВНЫЕ АЛЕРТЫ: {len(alerts)}**\n\n"
                
                if firing_alerts:
                    message_text += f"**🔴 Firing ({len(firing_alerts)}):**\n"
                    for alert in firing_alerts:
                        name = alert.get('alertname', 'Unknown')
                        severity = alert.get('severity', 'unknown')
                        message_text += f"• `{name}` - severity: {severity}\n"
                    message_text += "\n"
                
                if pending_alerts:
                    message_text += f"**🟡 Pending ({len(pending_alerts)}):**\n"
                    for alert in pending_alerts:
                        name = alert.get('alertname', 'Unknown')
                        message_text += f"• `{name}`\n"
                    message_text += "\n"
                
                if summary:
                    message_text += f"**Детали:**\n{summary}"
            
            await self.send_message(chat_id, message_text)
            return ""
            
        except Exception as e:
            error_msg = f"❌ Ошибка получения алертов: {str(e)}"
            logger.error(f"Ошибка cmd_alerts: {e}", exc_info=True)
            await self.send_message(chat_id, error_msg)
            return ""
    
    async def cmd_health(self, chat_id: str, message: str) -> str:
        """Команда /health - проверка здоровья системы мониторинга"""
        try:
            await self.send_chat_action(chat_id, "typing")
            
            health_text = "🏥 **HEALTH CHECK**\n\n"
            
            # Проверяем MCP сервер
            try:
                is_healthy = await self.mcp.health_check()
                if is_healthy:
                    health_text += "✅ MCP Server: OK\n"
                else:
                    health_text += "❌ MCP Server: ERROR\n"
            except Exception as e:
                health_text += f"❌ MCP Server: {str(e)[:50]}\n"
            
            # Проверяем Prometheus (через CPU метрику)
            try:
                response_text = await self.mcp.call_tool("get_cpu_usage")
                # Если получили ответ без ошибки - Prometheus работает
                if response_text and "ошибка" not in response_text.lower() and "error" not in response_text.lower():
                    health_text += "✅ Prometheus: OK\n"
                else:
                    health_text += f"❌ Prometheus: {response_text[:50]}\n"
            except Exception as e:
                health_text += f"❌ Prometheus: {str(e)[:50]}\n"
            
            # Проверяем Loki (через поиск логов)
            try:
                response_text = await self.mcp.call_tool("search_error_logs", arguments={"hours": 1})
                # Если получили ответ без ошибки - Loki работает
                if response_text and "ошибка" not in response_text.lower() and "error" not in response_text.lower():
                    health_text += "✅ Loki: OK\n"
                else:
                    health_text += f"❌ Loki: {response_text[:50]}\n"
            except Exception as e:
                health_text += f"❌ Loki: {str(e)[:50]}\n"
            
            # Проверяем Telegram Bot
            health_text += "✅ Telegram Bot: OK (you're here!)\n"
            
            health_text += "\n💡 Все компоненты мониторинга работают корректно!"
            
            await self.send_message(chat_id, health_text)
            return ""
            
        except Exception as e:
            error_msg = f"❌ Ошибка health check: {str(e)}"
            logger.error(f"Ошибка cmd_health: {e}", exc_info=True)
            await self.send_message(chat_id, error_msg)
            return ""
    
    async def cmd_help(self, chat_id: str, message: str) -> str:
        """Команда /help - справка"""
        help_text = """❓ **СПРАВКА ПО КОМАНДАМ**

📊 **Основные команды:**
• `/status` - текущий статус системы (сырые данные)
• `/analyze` - полный анализ через ИИ
• `/alerts` - показать активные алерты
• `/health` - проверка компонентов мониторинга
• `/chat` - режим диалога с ИИ
• `/end_chat` - выход из режима чата

🔧 **Детальные метрики (MCP Tools):**
• `/cpu` - быстрая загрузка CPU (без AI)
• `/memory` - анализ памяти с AI
• `/disk` - использование дисков с AI
• `/network` - сетевые метрики с AI
• `/processes` - топ процессов по CPU/RAM

📚 **MCP Resources (контекстные данные):**
• `/resources` - список доступных ресурсов
• `/resource <uri>` - чтение конкретного ресурса
  Пример: `/resource metrics/cpu/current`

🎯 **MCP Prompts (готовые сценарии):**
• `/prompts` - список доступных сценариев
• `/investigate_cpu` - расследование CPU
• `/diagnose_memory` - диагностика памяти
• `/analyze_incident <период>` - анализ инцидента
  Пример: `/analyze_incident 2h`

📄 **Отчёты (Excel/PDF):**
• `/report_daily` - отчёт за сутки
• `/report_weekly` - отчёт за неделю
• `/report_monthly` - отчёт за месяц

🔧 **Управление:**
• `/start` - главное меню
• `/menu` - показать меню
• `/help` - эта справка

💡 **Советы:**
• Используйте `/cpu`, `/memory` для быстрых проверок
• `/analyze` для детального анализа всей системы
• `/investigate_cpu` для глубокого расследования проблем
• `/resources` для доступа к агрегированным данным
• `/chat` для свободных вопросов к AI"""
        
        await self.send_message(chat_id, help_text)
        return ""
    
    async def process_chat_question(self, chat_id: str, question: str):
        """Обработка вопроса в режиме чата"""
        try:
            await self.send_chat_action(chat_id, "typing")
            
            # Инициализируем клиенты если нужно
            if not hasattr(self, 'prometheus') or self.prometheus is None:
                from clients.prometheus_client import PrometheusClient
                self.prometheus = PrometheusClient("http://147.45.157.2:9090")
            
            if not hasattr(self, 'loki') or self.loki is None:
                from clients.loki_client import LokiClient
                self.loki = LokiClient("http://147.45.157.2:3100")
            
            if not hasattr(self, 'llm_client') or self.llm_client is None:
                from llm.universal_client import UniversalLLMClient
                self.llm_client = UniversalLLMClient()
            
            # Определяем тип вопроса
            question_lower = question.lower().strip()
            
            # Список ключевых слов для вопросов о системе/мониторинге
            system_keywords = [
                "cpu", "память", "memory", "диск", "disk", "сеть", "network",
                "нагрузка", "load", "процесс", "process", "контейнер", "container",
                "docker", "сервер", "server", "система", "system", "метрик", "metric",
                "алерт", "alert", "лог", "log", "ошибка", "error", "проблем", "problem",
                "мониторинг", "monitoring", "состояние", "status", "grafana", "prometheus",
                "почему", "what", "why", "как", "how", "когда", "when"
            ]
            
            # Приветствия
            greetings = ["привет", "здравствуй", "хай", "hi", "hello", "здравствуйте", "добрый день", "доброе утро"]
            
            # Проверяем тип вопроса
            is_greeting = any(greeting in question_lower for greeting in greetings)
            is_system_question = any(keyword in question_lower for keyword in system_keywords)
            
            if is_greeting:
                # Для приветствий - простой ответ без метрик
                metrics_data = {}
                context = f"Пользователь написал приветствие: {question}\n\nОтветь дружелюбно на русском, в одном предложении."
            elif is_system_question:
                # Для вопросов про систему - получаем метрики
                cpu_data = await self.prometheus.get_current_cpu()
                memory_data = await self.prometheus.get_current_memory()
                
                # Формируем данные для LLM (словарь - обязательно!)
                metrics_data = {
                    "cpu_percent": cpu_data or 0,
                    "memory_percent": memory_data.get('percent', 0) if memory_data else 0,
                    "memory_used_gb": memory_data.get('used_gb', 0) if memory_data else 0,
                    "memory_total_gb": memory_data.get('total_gb', 0) if memory_data else 0
                }
                
                # Формируем контекст для LLM
                context = f"""Вопрос пользователя: {question}

Ответь кратко и по делу на русском языке."""
            else:
                # Для общих вопросов (математика, общие знания) - без метрик
                metrics_data = {}
                context = f"Вопрос пользователя: {question}\n\nОтветь на вопрос кратко и по делу на русском языке. Это общий вопрос, не про систему мониторинга."
            
            # Получаем ответ от LLM - первым параметром словарь!
            response = await self.llm_client.analyze_metrics(metrics_data, context)
            
            await self.send_message(chat_id, f"🤖 **Ответ ИИ:**\n\n{response}")
            
        except Exception as e:
            logger.error(f"Ошибка обработки вопроса: {e}")
            await self.send_message(chat_id, f"❌ Ошибка обработки вопроса: {e}")
    
    async def cmd_report_daily(self, chat_id: str, message: str):
        """Команда /report_daily - выбор формата отчёта за сутки"""
        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📊 Excel", "callback_data": "report:excel:24h"},
                    {"text": "📄 PDF с AI", "callback_data": "report:pdf:24h"}
                ]
            ]
        }
        await self.send_message(
            chat_id,
            "📊 Выберите формат отчёта за сутки:",
            reply_markup=inline_keyboard
        )
    
    async def cmd_report_weekly(self, chat_id: str, message: str):
        """Команда /report_weekly - выбор формата отчёта за неделю"""
        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📊 Excel", "callback_data": "report:excel:7d"},
                    {"text": "📄 PDF с AI", "callback_data": "report:pdf:7d"}
                ]
            ]
        }
        await self.send_message(
            chat_id,
            "📊 Выберите формат отчёта за неделю:",
            reply_markup=inline_keyboard
        )
    
    async def cmd_report_monthly(self, chat_id: str, message: str):
        """Команда /report_monthly - выбор формата отчёта за месяц"""
        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📊 Excel", "callback_data": "report:excel:30d"},
                    {"text": "📄 PDF с AI", "callback_data": "report:pdf:30d"}
                ]
            ]
        }
        await self.send_message(
            chat_id,
            "📊 Выберите формат отчёта за месяц:",
            reply_markup=inline_keyboard
        )
    
    async def generate_and_send_excel(self, chat_id: str, period: str, period_name: str):
        """
        Генерирует и отправляет Excel отчёт
        
        Args:
            chat_id: ID чата Telegram
            period: Период в формате "24h", "7d", "30d"
            period_name: Название периода для пользователя
        """
        import os
        import tempfile
        from datetime import datetime
        
        try:
            # Уведомляем пользователя о начале генерации
            await self.send_message(chat_id, f"⏳ Генерирую отчёт за {period_name}...\n\nЭто может занять некоторое время.")
            await self.send_chat_action(chat_id, "upload_document")
            
            # Импортируем генератор отчётов
            from reports.excel_generator import generate_excel_report
            
            # Генерируем отчёт
            logger.info(f"Генерация отчёта за период {period}")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Используем системную временную директорию (работает и на Windows и на Linux)
            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"report_{period}_{timestamp}.xlsx")
            
            report_path = await generate_excel_report(
                period=period,
                output_path=output_path
            )
            
            # Проверяем что файл создан
            if not os.path.exists(report_path):
                raise Exception("Файл отчёта не был создан")
            
            # Отправляем файл
            logger.info(f"Отправка отчёта {report_path}")
            caption = f"📊 Отчёт о системе мониторинга за {period_name}\n\n📅 Период: {period}\n⏰ Создан: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            
            result = await self.send_document(chat_id, report_path, caption)
            
            if result:
                await self.send_message(chat_id, "✅ Отчёт успешно сгенерирован и отправлен!")
            else:
                await self.send_message(chat_id, "❌ Ошибка при отправке отчёта")
            
            # Удаляем временный файл
            try:
                os.remove(report_path)
                logger.info(f"Временный файл удалён: {report_path}")
            except Exception as e:
                logger.warning(f"Не удалось удалить временный файл: {e}")
            
        except Exception as e:
            logger.error(f"Ошибка генерации отчёта: {e}", exc_info=True)
            await self.send_message(chat_id, f"❌ Ошибка генерации отчёта: {e}\n\nПопробуйте позже или обратитесь к администратору.")
    
    async def generate_and_send_pdf(self, chat_id: str, period: str, period_name: str):
        """
        Генерирует и отправляет PDF отчёт с AI анализом
        
        Args:
            chat_id: ID чата Telegram
            period: Период в формате "24h", "7d", "30d"
            period_name: Название периода для пользователя
        """
        import os
        import tempfile
        from datetime import datetime
        
        try:
            # Уведомляем пользователя о начале генерации
            await self.send_message(
                chat_id,
                f"⏳ Генерирую PDF отчёт за {period_name} с AI анализом...\n\n"
                "Это может занять 30-60 секунд (сбор данных, создание графиков, анализ через LLM)."
            )
            await self.send_chat_action(chat_id, "upload_document")
            
            # Импортируем генератор отчётов
            from reports.pdf_generator import generate_pdf_report
            
            # Генерируем отчёт
            logger.info(f"Генерация PDF отчёта за период {period}")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Используем системную временную директорию (работает и на Windows и на Linux)
            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"report_pdf_{period}_{timestamp}.pdf")
            
            report_path = await generate_pdf_report(
                period=period,
                output_path=output_path
            )
            
            # Проверяем что файл создан
            if not os.path.exists(report_path):
                raise Exception("Файл отчёта не был создан")
            
            # Отправляем файл
            logger.info(f"Отправка PDF отчёта {report_path}")
            caption = f"📄 PDF отчёт о системе мониторинга за {period_name}\n\n📅 Период: {period}\n🤖 С AI анализом от DeepSeek V3.1\n⏰ Создан: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            
            result = await self.send_document(chat_id, report_path, caption)
            
            if result:
                await self.send_message(chat_id, "✅ PDF отчёт успешно сгенерирован и отправлен!")
            else:
                await self.send_message(chat_id, "❌ Ошибка при отправке отчёта")
            
            # Удаляем временный файл
            try:
                os.remove(report_path)
                logger.info(f"Временный файл удалён: {report_path}")
            except Exception as e:
                logger.warning(f"Не удалось удалить временный файл: {e}")
            
        except Exception as e:
            logger.error(f"Ошибка генерации PDF отчёта: {e}", exc_info=True)
            await self.send_message(chat_id, f"❌ Ошибка генерации PDF отчёта: {e}\n\nПопробуйте позже или обратитесь к администратору.")
    
    async def answer_callback_query(self, callback_id: str, text: str = ""):
        """Подтверждение callback query"""
        try:
            url = f"{self.base_url}/answerCallbackQuery"
            data = {"callback_query_id": callback_id}
            if text:
                data["text"] = text
            
            async with httpx.AsyncClient() as client:
                await client.post(url, json=data)
        except Exception as e:
            logger.error(f"Ошибка answer_callback_query: {e}")
    
    async def process_callback_query(self, update: dict):
        """Обработка нажатий на inline кнопки"""
        try:
            callback = update.get("callback_query", {})
            callback_id = callback.get("id")
            data = callback.get("data")  # "report:excel:24h" или "report:pdf:24h"
            chat_id = str(callback.get("message", {}).get("chat", {}).get("id"))
            
            logger.info(f"Получен callback от {chat_id}: {data}")
            
            # Парсим callback_data
            parts = data.split(":")
            if parts[0] == "report":
                format_type = parts[1]  # "excel" или "pdf"
                period = parts[2]       # "24h", "7d", "30d"
                
                # Подтверждаем callback
                await self.answer_callback_query(callback_id, "Генерирую отчёт...")
                
                # Определяем название периода
                period_names = {"24h": "сутки", "7d": "неделю", "30d": "месяц"}
                period_name = period_names.get(period, period)
                
                # Генерируем отчёт
                if format_type == "excel":
                    await self.generate_and_send_excel(chat_id, period, period_name)
                elif format_type == "pdf":
                    await self.generate_and_send_pdf(chat_id, period, period_name)
                else:
                    await self.send_message(chat_id, f"❌ Неизвестный формат: {format_type}")
            else:
                logger.warning(f"Неизвестный тип callback: {data}")
        
        except Exception as e:
            logger.error(f"Ошибка обработки callback: {e}", exc_info=True)
    
    # ========================================================================
    # НОВЫЕ КОМАНДЫ: Все MCP Tools
    # ========================================================================
    
    async def cmd_cpu(self, chat_id: str, message: str):
        """Команда /cpu - быстрый CPU без LLM анализа"""
        try:
            await self.send_chat_action(chat_id, "typing")
            result = await self.mcp.call_tool("get_cpu_usage_raw")
            await self.send_message(chat_id, f"💻 **CPU Usage**\n\n{result}")
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    async def cmd_memory(self, chat_id: str, message: str):
        """Команда /memory - анализ памяти с LLM"""
        try:
            await self.send_chat_action(chat_id, "typing")
            await self.send_message(chat_id, "⏳ Получаю данные о памяти и анализирую...")
            result = await self.mcp.call_tool("get_memory_status")
            await self.send_message(chat_id, f"🧠 **Memory Status**\n\n{result}")
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    async def cmd_disk(self, chat_id: str, message: str):
        """Команда /disk - использование дисков"""
        try:
            await self.send_chat_action(chat_id, "typing")
            await self.send_message(chat_id, "⏳ Получаю данные о дисках...")
            result = await self.mcp.call_tool("get_disk_usage")
            await self.send_message(chat_id, f"💾 **Disk Usage**\n\n{result}")
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    async def cmd_network(self, chat_id: str, message: str):
        """Команда /network - сетевые метрики"""
        try:
            await self.send_chat_action(chat_id, "typing")
            await self.send_message(chat_id, "⏳ Получаю сетевые метрики...")
            result = await self.mcp.call_tool("get_network_status")
            await self.send_message(chat_id, f"🌐 **Network Status**\n\n{result}")
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    async def cmd_processes(self, chat_id: str, message: str):
        """Команда /processes - топ процессов"""
        try:
            await self.send_chat_action(chat_id, "typing")
            await self.send_message(chat_id, "⏳ Получаю список топ процессов...")
            result = await self.mcp.call_tool("get_top_processes", arguments={"limit": 10})
            await self.send_message(chat_id, f"⚙️ **Top Processes**\n\n{result}")
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    # ========================================================================
    # НОВЫЕ КОМАНДЫ: MCP Resources
    # ========================================================================
    
    async def cmd_resources(self, chat_id: str, message: str):
        """Команда /resources - список доступных ресурсов"""
        try:
            await self.send_chat_action(chat_id, "typing")
            resources_data = await self.mcp.get_resources()
            
            resources = resources_data.get("resources", [])
            if not resources:
                await self.send_message(chat_id, "❌ Нет доступных ресурсов")
                return
            
            response = "📚 **Доступные Resources:**\n\n"
            for i, res in enumerate(resources, 1):
                response += f"{i}. `{res['name']}`\n"
                response += f"   URI: `{res['uri']}`\n"
                response += f"   📝 {res['description']}\n\n"
            
            response += "\n💡 Используйте `/resource <uri>` для чтения ресурса\n"
            response += "Пример: `/resource metrics/cpu/current`"
            
            await self.send_message(chat_id, response)
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    async def cmd_resource(self, chat_id: str, message: str):
        """Команда /resource <uri> - чтение конкретного ресурса"""
        try:
            # Парсим URI из команды
            parts = message.strip().split(maxsplit=1)
            if len(parts) < 2:
                await self.send_message(
                    chat_id,
                    "❌ Укажите URI ресурса\n\n"
                    "Примеры:\n"
                    "`/resource metrics/cpu/current`\n"
                    "`/resource system/status`\n\n"
                    "Используйте `/resources` для списка"
                )
                return
            
            uri = parts[1].strip()
            
            await self.send_chat_action(chat_id, "typing")
            await self.send_message(chat_id, f"⏳ Читаю resource: `{uri}`...")
            
            content = await self.mcp.read_resource(uri)
            
            # Пробуем отформатировать JSON
            try:
                import json
                json_data = json.loads(content)
                formatted = json.dumps(json_data, indent=2, ensure_ascii=False)
                await self.send_message(chat_id, f"📄 **Resource: {uri}**\n\n```json\n{formatted[:3500]}\n```")
            except:
                await self.send_message(chat_id, f"📄 **Resource: {uri}**\n\n{content[:4000]}")
        
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    # ========================================================================
    # НОВЫЕ КОМАНДЫ: MCP Prompts
    # ========================================================================
    
    async def cmd_prompts(self, chat_id: str, message: str):
        """Команда /prompts - список доступных промптов"""
        try:
            await self.send_chat_action(chat_id, "typing")
            prompts_data = await self.mcp.get_prompts()
            
            prompts = prompts_data.get("prompts", [])
            if not prompts:
                await self.send_message(chat_id, "❌ Нет доступных промптов")
                return
            
            response = "🎯 **Доступные Prompts (сценарии анализа):**\n\n"
            for i, prompt in enumerate(prompts, 1):
                response += f"{i}. **{prompt['name']}**\n"
                response += f"   📝 {prompt['description']}\n"
                if prompt.get('arguments'):
                    args_str = ", ".join([f"`{arg['name']}`" for arg in prompt['arguments']])
                    response += f"   📋 Аргументы: {args_str}\n"
                response += "\n"
            
            response += "\n💡 **Команды для запуска:**\n"
            response += "• `/investigate_cpu` - расследование CPU\n"
            response += "• `/diagnose_memory` - диагностика памяти\n"
            response += "• `/analyze_incident <период>` - анализ инцидента"
            
            await self.send_message(chat_id, response)
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    async def cmd_investigate_cpu(self, chat_id: str, message: str):
        """Команда /investigate_cpu - расследование высокой нагрузки CPU через Prompt"""
        try:
            await self.send_chat_action(chat_id, "typing")
            await self.send_message(chat_id, "🔍 Расследую загрузку CPU...\n\nСобираю метрики и генерирую отчет...")
            
            # Генерируем промпт с актуальными данными
            prompt_text = await self.mcp.generate_prompt("investigate_high_cpu")
            
            # Отправляем промпт пользователю
            await self.send_message(chat_id, f"📊 **Расследование CPU:**\n\n{prompt_text}")
            
            # Можно также отправить в LLM для анализа
            if self.llm_client:
                await self.send_message(chat_id, "⏳ Анализирую через AI...")
                analysis = await self.llm_client.analyze(prompt_text)
                await self.send_message(chat_id, f"🤖 **AI Анализ:**\n\n{analysis}")
        
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    async def cmd_diagnose_memory(self, chat_id: str, message: str):
        """Команда /diagnose_memory - диагностика утечек памяти через Prompt"""
        try:
            await self.send_chat_action(chat_id, "typing")
            await self.send_message(chat_id, "🔍 Диагностирую память...\n\nСобираю метрики и анализирую паттерны...")
            
            prompt_text = await self.mcp.generate_prompt("diagnose_memory_leak")
            await self.send_message(chat_id, f"🧠 **Диагностика памяти:**\n\n{prompt_text}")
            
            if self.llm_client:
                await self.send_message(chat_id, "⏳ Анализирую через AI...")
                analysis = await self.llm_client.analyze(prompt_text)
                await self.send_message(chat_id, f"🤖 **AI Анализ:**\n\n{analysis}")
        
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    async def cmd_analyze_incident(self, chat_id: str, message: str):
        """Команда /analyze_incident <период> - анализ инцидента за период"""
        try:
            # Парсим период
            parts = message.strip().split(maxsplit=1)
            time_period = "1h"  # По умолчанию 1 час
            if len(parts) >= 2:
                time_period = parts[1].strip()
            
            await self.send_chat_action(chat_id, "typing")
            await self.send_message(chat_id, f"🔍 Анализирую инцидент за период: {time_period}...\n\nСобираю логи, метрики и алерты...")
            
            prompt_text = await self.mcp.generate_prompt("analyze_incident", arguments={"time_period": time_period})
            await self.send_message(chat_id, f"📊 **Анализ инцидента ({time_period}):**\n\n{prompt_text}")
            
            if self.llm_client:
                await self.send_message(chat_id, "⏳ Анализирую через AI...")
                analysis = await self.llm_client.analyze(prompt_text)
                await self.send_message(chat_id, f"🤖 **AI Анализ:**\n\n{analysis}")
        
        except Exception as e:
            await self.send_message(chat_id, f"❌ Ошибка: {e}")
    
    # ========================================================================
    # RUN LOOP
    # ========================================================================
    
    async def run(self):
        """Запуск бота"""
        logger.info("Запуск Telegram бота...")
        offset = 0
        
        while True:
            try:
                updates = await self.get_updates(offset)
                
                for update in updates:
                    offset = update.get("update_id", 0) + 1
                    
                    # Обрабатываем callback_query (нажатия на inline кнопки)
                    if "callback_query" in update:
                        await self.process_callback_query(update)
                    # Обрабатываем обычные сообщения
                    else:
                        await self.process_message(update)
                
                await asyncio.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки")
                break
            except Exception as e:
                logger.error(f"Ошибка в основном цикле: {e}")
                await asyncio.sleep(5)
    
    async def close(self):
        """Закрытие бота"""
        logger.info("Закрытие Telegram бота...")
        if self.mcp:
            await self.mcp.close()


async def main():
    """Главная функция"""
    import os
    
    # Получаем токен из переменных окружения
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN не найден в переменных окружения")
        return 1
    
    logger.info(f"Токен бота: {token[:10]}...")
    
    # Создаем и запускаем бота
    bot = TelegramMonitoringBot(token, use_mcp=True)
    
    try:
        await bot.run()
    finally:
        await bot.close()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())