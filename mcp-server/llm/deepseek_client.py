"""
DeepSeek V3.1 API Client для анализа метрик
"""
import os
import httpx
import json
from typing import Dict, Any, Optional
from loguru import logger


class DeepSeekClient:
    """Клиент для работы с DeepSeek V3.1 API через TimeWeb"""
    
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = "https://agent.timeweb.cloud/api/v1/cloud-ai/agents/38478adf-99ed-4614-9eb2-2c59f55f206c/v1"
        self.model = "deepseek-chat"
        
        # Настройки из .env файла
        self.max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "320"))
        self.temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.2"))
        
        if not self.api_key or self.api_key == "your_deepseek_api_key_here":
            logger.warning("DEEPSEEK_API_KEY не настроен, LLM анализ отключен")
            self.api_key = None
            return
    
    async def analyze_metrics(self, metrics_data: Dict[str, Any], context: str = "") -> str:
        """Анализ метрик через DeepSeek V3.1"""
        if not self.api_key:
            return "LLM анализ недоступен: DEEPSEEK_API_KEY не настроен"
            
        try:
            # Формируем промпт
            prompt = self._build_prompt(metrics_data, context)
            
            # Отправляем запрос
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Отправляем запрос к DeepSeek API: {self.base_url}/chat/completions")
                logger.info(f"Модель: {self.model}, max_tokens: {self.max_tokens}, temperature: {self.temperature}")
                
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"{self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": self.system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": self.max_tokens,
                        "temperature": self.temperature
                    }
                )
                
                logger.info(f"DeepSeek API ответ: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"Ошибка DeepSeek API: {response.status_code} - {response.text}")
                    return f"Ошибка анализа: HTTP {response.status_code}"
                
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                logger.info(f"DeepSeek API успешно обработан")
                logger.info(f"Ответ DeepSeek: {content[:200]}...")  # Первые 200 символов
                return content
                    
        except Exception as e:
            logger.error(f"Ошибка при запросе к DeepSeek: {e}")
            return f"Ошибка анализа: {str(e)}"
    
    def _build_prompt(self, metrics_data: Dict[str, Any], context: str) -> str:
        """Построение промпта для анализа"""
        prompt = ""
        
        # Если есть метрики, показываем их
        if metrics_data and len(metrics_data) > 0:
            prompt += "Метрики системы:\n"
            for key, value in metrics_data.items():
                prompt += f"- {key}: {value}\n"
            prompt += "\n"
        
        # Добавляем контекст (вопрос пользователя или другой контекст)
        if context:
            prompt += f"Контекст: {context}\n\n"
        
        # Если есть метрики - просим проанализировать, если нет - просто отвечать
        if metrics_data and len(metrics_data) > 0:
            prompt += "Проанализируй состояние системы и дай рекомендации."
        else:
            prompt += "Ответь на вопрос пользователя естественно, без формата анализа."
        
        return prompt
    
    @property
    def system_prompt(self) -> str:
        """Системный промпт для анализа метрик"""
        return """Ты - опытный DevOps инженер и эксперт по мониторингу.

Контекст системы:
- В инфраструктуре уже развернуты Grafana дашборды и алертинг.
- Не предлагай «настроить мониторинг/алерты с нуля». Вместо этого предлагай:
  • подстройку порогов, задержек и каналов оповещений;
  • добавление панелей/аннотаций/переменных в существующие дашборды;
  • проверку связности экспортеров и источников данных;
  • SLO/SLA и валидацию правил алертинга.

ВАЖНО: Если в данных есть "Active Alerts" с состоянием "firing" - это КРИТИЧЕСКИЙ сигнал!
- Алерт "HighCPUUsage" означает, что CPU был загружен на 80%+ 
- Алерт "HighMemoryUsage" означает, что память была загружена на 85%+
- Алерт "HighDiskUsage" означает, что диск был загружен на 90%+

Твоя задача:
1) Проанализировать метрики (CPU, память, диски, сеть, процессы, контейнеры cAdvisor).
2) ОБЯЗАТЕЛЬНО учесть активные алерты - они показывают реальные проблемы!
3) ОБЯЗАТЕЛЬНО учесть 5-минутные тренды (min/avg/max, direction) для CPU, памяти, дисков и сети.
4) Определить проблемы и их критичность.
5) Дать конкретные, выполнимые рекомендации (без общих фраз).
6) Сформировать краткий прогноз при росте нагрузки.

Уровни критичности:
- КРИТИЧНО (>95% ИЛИ есть активные алерты): немедленные действия
- ВНИМАНИЕ (>80% ИЛИ недавние алерты): требуется внимание  
- НОРМА (<порогов И нет алертов): все в порядке

Формат ответа строго из 4 разделов и без обрывов. Каждый пункт 1 предложение, общий ответ <300 символов, избегай повторов и общих фраз:
1. СТАТУС: … (обязательно упомяни активные алерты если есть!)
2. ПРОБЛЕМЫ: … (если есть алерты - это проблемы!)
3. РЕКОМЕНДАЦИИ: … (только конкретные действия; можно упоминать настройку порогов/панелей в Grafana)
4. ПРОГНОЗ: … (в т.ч. что произойдёт при росте нагрузки в 2–3 раза)

Отвечай ТОЛЬКО на русском языке, кратко и по делу, но без усечений разделов.

Если пользователь задает общий вопрос (не про анализ метрик), отвечай естественно и по делу, без строгого формата из 4 разделов."""
    
    async def generate_report_analysis(self, data: Dict[str, Any], period: str) -> str:
        """
        Генерирует полный анализ для PDF отчёта
        
        Args:
            data: Собранные метрики за период (из collect_metrics_for_period)
            period: Период отчёта ("24h", "7d", "30d")
            
        Returns:
            Текст анализа с разделами:
            - Общее состояние системы
            - Выявленные проблемы
            - Анализ трендов
            - Прогноз на будущее
            - Конкретные рекомендации
        """
        if not self.api_key:
            return "LLM анализ недоступен: DEEPSEEK_API_KEY не настроен"
        
        try:
            # Формируем расширенный промпт для отчёта
            prompt = self._build_report_prompt(data, period)
            
            # Системный промпт для отчётов
            system_prompt = """Ты - эксперт DevOps инженер и специалист по мониторингу систем.

Твоя задача - создать детальный профессиональный анализ состояния системы мониторинга за указанный период.

Структура ответа (обязательно включи все разделы):

# 1. ОБЩЕЕ СОСТОЯНИЕ СИСТЕМЫ
Краткая сводка: критичность ситуации, главные показатели, общая оценка здоровья системы.

# 2. ВЫЯВЛЕННЫЕ ПРОБЛЕМЫ
Детальный список проблем с указанием:
- Что именно не так
- Какие метрики показывают проблему
- Когда это началось (если видно из трендов)
- Уровень критичности

# 3. АНАЛИЗ ТРЕНДОВ
Анализ динамики метрик:
- Что растёт/падает/стабильно
- Сравнение начала и конца периода
- Выявление паттернов (пики нагрузки, цикличность)
- Корреляции между метриками

# 4. ПРОГНОЗ НА БУДУЩЕЕ
- Что произойдёт если тренды продолжатся
- Когда ожидается исчерпание ресурсов
- Риски при росте нагрузки в 2-3 раза
- Предупреждения о потенциальных проблемах

# 5. КОНКРЕТНЫЕ РЕКОМЕНДАЦИИ
Действия по приоритетам:
- СРОЧНО: что требует немедленного внимания
- ВАЖНО: что нужно сделать в ближайшее время
- РЕКОМЕНДУЕТСЯ: улучшения для оптимизации

Каждая рекомендация должна быть:
- Конкретной и выполнимой
- С указанием на какую метрику повлияет
- С приоритетом (критично/важно/рекомендуется)

Пиши профессионально, но понятно. Избегай общих фраз типа "настроить мониторинг" - давай конкретные действия.
Используй данные из метрик для обоснования выводов. Будь честным - если данных недостаточно, так и скажи."""
            
            # Отправляем запрос с увеличенными лимитами
            # Увеличиваем timeout для больших периодов (30d может требовать больше времени)
            timeout_seconds = 120.0 if period == "30d" else 90.0
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                logger.info(f"Генерация полного анализа отчёта за период {period} (timeout: {timeout_seconds}s)")
                
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"{self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": system_prompt
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "max_tokens": 1500,  # Больше для детального анализа
                        "temperature": 0.3   # Чуть более креативно
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                    
                    if content:
                        logger.info("Полный анализ отчёта получен успешно")
                        return content
                    else:
                        return "Ошибка: пустой ответ от LLM"
                else:
                    error_text = response.text
                    logger.error(f"Ошибка API: {response.status_code} - {error_text}")
                    return f"Ошибка получения анализа: {response.status_code}"
                    
        except Exception as e:
            logger.error(f"Ошибка генерации анализа отчёта: {e}", exc_info=True)
            return f"Ошибка генерации анализа: {str(e)}"
    
    def _build_report_prompt(self, data: Dict[str, Any], period: str) -> str:
        """Построение промпта для анализа отчёта"""
        period_names = {"24h": "сутки", "7d": "неделю", "30d": "месяц"}
        period_name = period_names.get(period, period)
        
        prompt = f"Проанализируй состояние системы мониторинга за {period_name} ({period}).\n\n"
        
        # CPU
        cpu = data.get('cpu', {})
        prompt += f"## CPU:\n"
        prompt += f"- Текущее: {cpu.get('current', 0):.2f}%\n"
        prompt += f"- Среднее: {cpu.get('avg', 0):.2f}%\n"
        prompt += f"- Медиана: {cpu.get('median', 0):.2f}%\n"
        prompt += f"- Минимум: {cpu.get('min', 0):.2f}%\n"
        prompt += f"- Максимум: {cpu.get('max', 0):.2f}%\n"
        prompt += f"- 95 процентиль: {cpu.get('p95', 0):.2f}%\n"
        prompt += f"- Тренд: {cpu.get('trend', 'N/A')}\n\n"
        
        # Memory
        memory = data.get('memory', {})
        prompt += f"## Memory:\n"
        prompt += f"- Общая память: {memory.get('total_gb', 0):.2f} GB\n"
        prompt += f"- Текущее: {memory.get('current', 0):.2f}%\n"
        prompt += f"- Среднее: {memory.get('avg', 0):.2f}%\n"
        prompt += f"- Медиана: {memory.get('median', 0):.2f}%\n"
        prompt += f"- Минимум: {memory.get('min', 0):.2f}%\n"
        prompt += f"- Максимум: {memory.get('max', 0):.2f}%\n"
        prompt += f"- 95 процентиль: {memory.get('p95', 0):.2f}%\n"
        prompt += f"- Тренд: {memory.get('trend', 'N/A')}\n\n"
        
        # Disk
        disk = data.get('disk', {})
        prompt += f"## Диски:\n"
        disks = disk.get('disks', [])
        if disks:
            for d in disks:
                prompt += f"- {d.get('mountpoint', '/')}: {d.get('percent', 0):.1f}% ({d.get('used_gb', 0):.1f}/{d.get('total_gb', 0):.1f} GB)\n"
        prompt += f"- IO Read (avg): {disk.get('io_read_avg_mb', 0):.2f} MB/s\n"
        prompt += f"- IO Write (avg): {disk.get('io_write_avg_mb', 0):.2f} MB/s\n\n"
        
        # Network
        network = data.get('network', {})
        prompt += f"## Сеть:\n"
        prompt += f"- Status: {network.get('status', 'unknown')}\n"
        prompt += f"- RX (avg): {network.get('rx_avg_mb', 0):.2f} MB/s\n"
        prompt += f"- TX (avg): {network.get('tx_avg_mb', 0):.2f} MB/s\n"
        prompt += f"- Errors (avg): {network.get('errors_avg', 0):.2f}/s\n"
        connections = network.get('connections', {})
        prompt += f"- TCP connections: {connections.get('tcp_established', 0)}\n\n"
        
        # Alerts
        alerts = data.get('alerts', [])
        prompt += f"## Алерты ({len(alerts)} всего):\n"
        if alerts:
            firing = [a for a in alerts if a.get('state') in ['firing_now', 'firing']]
            historical = [a for a in alerts if a.get('state') == 'fired_in_period']
            
            if firing:
                prompt += f"АКТИВНЫЕ СЕЙЧАС ({len(firing)}):\n"
                for alert in firing:
                    prompt += f"- {alert.get('name', 'Unknown')}: severity={alert.get('severity', 'unknown')}, срабатываний={alert.get('firing_count', 0)}\n"
            
            if historical:
                prompt += f"\nСРАБАТЫВАЛИ ЗА ПЕРИОД ({len(historical)}):\n"
                for alert in historical[:5]:  # Топ 5
                    prompt += f"- {alert.get('name', 'Unknown')}: срабатываний={alert.get('firing_count', 0)}, первое={alert.get('first_fired', 'N/A')}, последнее={alert.get('last_fired', 'N/A')}\n"
        else:
            prompt += "Алертов не было\n"
        prompt += "\n"
        
        # Errors
        errors = data.get('errors', [])
        prompt += f"## Ошибки в логах ({len(errors)} записей):\n"
        if errors:
            # Показываем первые 5 ошибок
            for error in errors[:5]:
                container = error.get('container', 'unknown')
                message = error.get('message', '')[:100]  # Первые 100 символов
                prompt += f"- [{container}] {message}...\n"
        else:
            prompt += "Критичных ошибок в логах не обнаружено\n"
        prompt += "\n"
        
        # Top Processes
        processes = data.get('processes', [])
        prompt += f"## Топ процессов по CPU ({len(processes)} процессов):\n"
        for proc in processes[:5]:  # Топ 5
            prompt += f"- {proc.get('name', 'unknown')}: {proc.get('cpu_usage', 0):.2f}%\n"
        
        prompt += "\n---\n\nСоздай детальный профессиональный анализ на основе этих данных."
        
        return prompt