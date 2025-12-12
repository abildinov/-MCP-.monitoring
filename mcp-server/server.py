"""
MCP Server для мониторинга серверной инфраструктуры
Предоставляет tools для работы с Prometheus, Loki и анализа через DeepSeek V3.1
"""

import asyncio
import sys
from datetime import datetime
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool, TextContent,
    Resource, Prompt, PromptArgument, PromptMessage
)

from clients.prometheus_client import PrometheusClient
from clients.loki_client import LokiClient
from llm.universal_client import UniversalLLMClient
from config import settings
from loguru import logger

# Импорт системы алертов
from alerts.alert_manager import AlertManager
from alerts.telegram_notifier import TelegramNotifier

# Импорт детектора аномалий
from analytics.statistical_detector import StatisticalAnomalyDetector, Anomaly

# HTTP API для Telegram бота
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

# Настройка логирования
logger.remove()
logger.add(
    sys.stderr,
    level=settings.log_level,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
)

# Инициализация глобальных клиентов
prometheus_client: PrometheusClient = None
loki_client: LokiClient = None
llm_client: UniversalLLMClient = None
alert_manager: AlertManager = None
telegram_notifier: TelegramNotifier = None
anomaly_detector: StatisticalAnomalyDetector = None

# История метрик для детекции аномалий
metric_history = {
    'cpu_usage': [],
    'memory_usage': [],
    'disk_usage': [],
    'network_errors': []
}

# Cooldown для предотвращения спама алертов (ключ: метрика_тип_детекции -> последнее время отправки)
alert_cooldown = {}
ALERT_COOLDOWN_MINUTES = 10  # Не отправлять повторные алерты чаще чем раз в 10 минут

# HTTP API для Telegram бота
http_app = FastAPI(title="MCP Monitoring API", version="1.0.0")

# Создание MCP сервера
# ПРИМЕЧАНИЕ: В mcp==1.17.0 capabilities устанавливаются автоматически
# на основе зарегистрированных декораторов (@app.list_resources, @app.list_prompts и т.д.)
app = Server(settings.mcp_server_name)

logger.info(f"Инициализация {settings.mcp_server_name} v{settings.mcp_server_version}")


async def init_clients():
    """Инициализация клиентов при старте сервера"""
    global prometheus_client, loki_client, llm_client, alert_manager, telegram_notifier, anomaly_detector
    
    logger.info("Инициализация клиентов...")
    
    prometheus_client = PrometheusClient(settings.prometheus_url, settings.http_timeout)
    loki_client = LokiClient(settings.loki_url, settings.http_timeout)
    llm_client = UniversalLLMClient()
    
    # Проверка доступности
    prom_ok = await prometheus_client.check_health()
    loki_ok = await loki_client.check_health()
    llm_ok = await llm_client.check_health()
    
    logger.info(f"Статус клиентов - Prometheus: {prom_ok}, Loki: {loki_ok}, LLM: {llm_ok}")
    
    # Инициализация системы алертов
    alert_manager = AlertManager()
    logger.info(f"AlertManager инициализирован с {len(alert_manager.rules)} правилами")
    
    # Инициализация детектора аномалий с более строгими порогами
    anomaly_detector = StatisticalAnomalyDetector(
        zscore_threshold=3.0,      # Стандартный порог для статистических аномалий
        spike_factor=1.8,          # 180% скачок - обнаружит рост с 50% до 90%
        drift_threshold=0.30,      # 30% изменение - обнаруживает постепенный рост нагрузки
        min_history_size=3         # 3 точки - быстрая детекция пиков (вместо 10)
    )
    logger.info("✅ StatisticalAnomalyDetector инициализирован (БЫСТРАЯ ДЕТЕКЦИЯ)")
    
    # Инициализация Telegram уведомителя (если включен)
    if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
        telegram_notifier = TelegramNotifier(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id
        )
        
        # Проверяем подключение к Telegram
        telegram_ok = await telegram_notifier.test_connection()
        if telegram_ok:
            # Добавляем уведомитель в AlertManager
            alert_manager.add_notifier(telegram_notifier)
            logger.info("✅ Telegram уведомления включены")
        else:
            logger.error("❌ Не удалось подключиться к Telegram API")
    else:
        logger.warning("⚠️ Telegram уведомления отключены (проверьте настройки в .env)")
    
    if not all([prom_ok, loki_ok, llm_ok]):
        logger.warning("Некоторые клиенты недоступны, но сервер продолжит работу")


async def cleanup_clients():
    """Очистка ресурсов при завершении"""
    global prometheus_client, loki_client, llm_client, telegram_notifier
    
    logger.info("Закрытие клиентов...")
    
    if prometheus_client:
        await prometheus_client.close()
    if loki_client:
        await loki_client.close()
    if llm_client:
        await llm_client.close()
    if telegram_notifier:
        await telegram_notifier.close()


# ============================================================================
# MCP RESOURCES (Application-controlled contextual data)
# ============================================================================

@app.list_resources()
async def list_resources() -> list[Resource]:
    """Список доступных ресурсов для LLM"""
    return [
        Resource(
            uri="monitoring://metrics/cpu/current",
            name="Current CPU Metrics",
            description="Real-time CPU usage with trends (5min avg, max, direction)",
            mimeType="application/json"
        ),
        Resource(
            uri="monitoring://metrics/memory/current",
            name="Current Memory Metrics",
            description="Real-time memory usage with trends",
            mimeType="application/json"
        ),
        Resource(
            uri="monitoring://logs/errors/recent",
            name="Recent Error Logs",
            description="Error logs from the last hour",
            mimeType="text/plain"
        ),
        Resource(
            uri="monitoring://alerts/active",
            name="Active Alerts",
            description="Currently firing alerts from Prometheus",
            mimeType="application/json"
        ),
        Resource(
            uri="monitoring://system/status",
            name="System Status Summary",
            description="Complete system health status (CPU, Memory, Disk, Network)",
            mimeType="application/json"
        )
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    """Чтение ресурса по URI с реальными данными"""
    import json
    
    try:
        if uri == "monitoring://metrics/cpu/current":
            cpu_current = await prometheus_client.get_current_cpu()
            cpu_max_5m = await prometheus_client.get_cpu_max_last_minutes(5)
            cpu_trend = await prometheus_client.get_cpu_series_5m()
            
            data = {
                "current": cpu_current,
                "max_5m": cpu_max_5m,
                "trend": {
                    "min": cpu_trend.get("min", 0),
                    "avg": cpu_trend.get("avg", 0),
                    "max": cpu_trend.get("max", 0),
                    "direction": cpu_trend.get("direction", "flat"),
                    "arrow": cpu_trend.get("arrow", "→")
                },
                "threshold": settings.cpu_threshold,
                "status": "high" if cpu_current and cpu_current > settings.cpu_threshold else "normal"
            }
            return json.dumps(data, indent=2)
        
        elif uri == "monitoring://metrics/memory/current":
            memory = await prometheus_client.get_current_memory()
            mem_trend = await prometheus_client.get_memory_series_5m()
            
            data = {
                **memory,
                "trend_5m": {
                    "min": mem_trend.get("min", 0),
                    "avg": mem_trend.get("avg", 0),
                    "max": mem_trend.get("max", 0),
                    "direction": mem_trend.get("direction", "flat")
                },
                "threshold": settings.memory_threshold,
                "status": "high" if memory and memory.get('percent', 0) > settings.memory_threshold else "normal"
            }
            return json.dumps(data, indent=2)
        
        elif uri == "monitoring://logs/errors/recent":
            errors = await loki_client.get_error_logs(hours=1, limit=20)
            
            if not errors:
                return "No errors in the last hour"
            
            result = f"Recent Errors ({len(errors)} found):\n\n"
            for i, err in enumerate(errors[:10], 1):
                result += f"{i}. [{err['timestamp']}] {err['container']}\n"
                result += f"   {err['message'][:200]}\n\n"
            
            return result
        
        elif uri == "monitoring://alerts/active":
            alerts_text = await get_active_alerts()
            
            # Парсим текст алертов в JSON
            if "No active alerts" in alerts_text:
                return json.dumps({"active_alerts": [], "count": 0})
            
            return json.dumps({
                "active_alerts": alerts_text,
                "count": alerts_text.count("🔴") + alerts_text.count("🟡")
            }, indent=2)
        
        elif uri == "monitoring://system/status":
            # Полный статус системы
            cpu = await prometheus_client.get_current_cpu()
            memory = await prometheus_client.get_current_memory()
            disk = await prometheus_client.get_disk_usage()
            network = await prometheus_client.get_network_status()
            alerts = await get_active_alerts()
            
            data = {
                "cpu": {"current": cpu, "threshold": settings.cpu_threshold},
                "memory": memory,
                "disks": disk,
                "network": {"status": network.get('status', 'unknown') if network else 'unknown'},
                "active_alerts": alerts,
                "timestamp": __import__('datetime').datetime.now().isoformat()
            }
            return json.dumps(data, indent=2)
        
        else:
            return json.dumps({"error": f"Unknown resource URI: {uri}"})
    
    except Exception as e:
        logger.exception(f"Error reading resource {uri}")
        return json.dumps({"error": str(e)})


@app.subscribe_resource()
async def subscribe_resource(uri: str):
    """Подписка на изменения ресурса (placeholder для будущей реализации)"""
    logger.info(f"Client subscribed to resource: {uri}")
    # В будущем: добавить механизм push-уведомлений при изменении ресурса


@app.unsubscribe_resource()
async def unsubscribe_resource(uri: str):
    """Отписка от изменений ресурса"""
    logger.info(f"Client unsubscribed from resource: {uri}")


# ============================================================================
# MCP PROMPTS (User-controlled interactive templates)
# ============================================================================

@app.list_prompts()
async def list_prompts() -> list[Prompt]:
    """Список доступных промптов для типовых сценариев анализа"""
    return [
        Prompt(
            name="analyze_server_health",
            description="Comprehensive server health analysis with CPU, Memory, Disk, Network metrics",
            arguments=[
                PromptArgument(
                    name="detail_level",
                    description="Analysis detail: brief, normal, or detailed",
                    required=False
                )
            ]
        ),
        Prompt(
            name="investigate_high_cpu",
            description="Step-by-step CPU usage investigation with process analysis",
            arguments=[]
        ),
        Prompt(
            name="diagnose_memory_leak",
            description="Memory leak diagnostic workflow with trend analysis",
            arguments=[]
        ),
        Prompt(
            name="analyze_incident",
            description="Incident analysis for specific time period with logs and metrics",
            arguments=[
                PromptArgument(
                    name="time_period",
                    description="Time period (e.g., '1h', '30m', '2h')",
                    required=True
                )
            ]
        )
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: dict = None) -> PromptMessage:
    """Возвращает готовый промпт для LLM с актуальными данными"""
    import json
    
    arguments = arguments or {}
    
    if name == "analyze_server_health":
        detail_level = arguments.get("detail_level", "normal")
        
        # Собираем метрики
        cpu = await prometheus_client.get_current_cpu()
        memory = await prometheus_client.get_current_memory()
        disk = await prometheus_client.get_disk_usage()
        network = await prometheus_client.get_network_status()
        alerts = await get_active_alerts()
        
        prompt_text = f"""Проанализируй текущее состояние сервера. Уровень детализации: {detail_level}

МЕТРИКИ:
CPU: {cpu:.2f}% (threshold: {settings.cpu_threshold}%)
Memory: {memory.get('percent', 0):.2f}% (used: {memory.get('used_gb', 0):.2f}GB / {memory.get('total_gb', 0):.2f}GB)
Disks: {len(disk) if disk else 0} устройств
Network: {network.get('status', 'unknown') if network else 'unknown'}

АКТИВНЫЕ АЛЕРТЫ:
{alerts}

ЗАДАЧИ:
1. Оцени общее состояние системы (OK/Warning/Critical)
2. Выяви потенциальные проблемы
3. Дай рекомендации по оптимизации
{"4. Предоставь детальный анализ каждого компонента" if detail_level == "detailed" else ""}
"""
        return PromptMessage(
            role="user",
            content=TextContent(type="text", text=prompt_text)
        )
    
    elif name == "investigate_high_cpu":
        cpu = await prometheus_client.get_current_cpu()
        cpu_trend = await prometheus_client.get_cpu_series_5m()
        processes = await prometheus_client.get_top_processes_by_cpu(10)
        
        prompt_text = f"""Проведи расследование высокой загрузки CPU.

ТЕКУЩЕЕ СОСТОЯНИЕ:
- CPU Usage: {cpu:.2f}%
- Trend (5min): {cpu_trend.get('direction', 'flat')} {cpu_trend.get('arrow', '→')}
- Min/Avg/Max: {cpu_trend.get('min', 0):.1f}/{cpu_trend.get('avg', 0):.1f}/{cpu_trend.get('max', 0):.1f}%

TOP ПРОЦЕССЫ:
"""
        for proc in processes[:5]:
            prompt_text += f"- {proc['name']}: {proc['cpu_usage']:.2f}%\n"
        
        prompt_text += """
ЗАДАЧИ:
1. Определи причину высокой нагрузки CPU
2. Оцени является ли это нормальным или аномалией
3. Предложи шаги для решения проблемы
4. Оцени риски для системы
"""
        return PromptMessage(
            role="user",
            content=TextContent(type="text", text=prompt_text)
        )
    
    elif name == "diagnose_memory_leak":
        memory = await prometheus_client.get_current_memory()
        mem_trend = await prometheus_client.get_memory_series_5m()
        mem_processes = await prometheus_client.get_top_processes_by_memory(10)
        
        prompt_text = f"""Диагностика потенциальной утечки памяти.

ТЕКУЩЕЕ СОСТОЯНИЕ:
- Memory Usage: {memory.get('percent', 0):.2f}%
- Used: {memory.get('used_gb', 0):.2f}GB / {memory.get('total_gb', 0):.2f}GB
- Available: {memory.get('available_gb', 0):.2f}GB
- Trend (5min): {mem_trend.get('direction', 'flat')} {mem_trend.get('arrow', '→')}

TOP ПРОЦЕССЫ ПО ПАМЯТИ:
"""
        for proc in mem_processes[:5]:
            prompt_text += f"- {proc['name']}: {proc['memory_usage_gb']:.2f}GB ({proc['memory_percent']:.1f}%)\n"
        
        prompt_text += """
ЗАДАЧИ:
1. Проанализируй паттерн использования памяти
2. Определи есть ли признаки memory leak
3. Выяви процессы-подозреваемые
4. Предложи план действий для диагностики и решения
"""
        return PromptMessage(
            role="user",
            content=TextContent(type="text", text=prompt_text)
        )
    
    elif name == "analyze_incident":
        time_period = arguments.get("time_period", "1h")
        
        # Парсим time_period (например "1h" -> 1 час)
        hours = 1
        if time_period.endswith('h'):
            hours = int(time_period[:-1])
        elif time_period.endswith('m'):
            hours = int(time_period[:-1]) / 60
        
        # Собираем данные
        errors = await loki_client.get_error_logs(hours=hours, limit=20)
        cpu = await prometheus_client.get_current_cpu()
        memory = await prometheus_client.get_current_memory()
        alerts = await get_active_alerts()
        
        prompt_text = f"""Анализ инцидента за период: {time_period}

ТЕКУЩИЕ МЕТРИКИ:
- CPU: {cpu:.2f}%
- Memory: {memory.get('percent', 0):.2f}%

ОШИБКИ В ЛОГАХ ({len(errors) if errors else 0} найдено):
"""
        if errors:
            for i, err in enumerate(errors[:5], 1):
                prompt_text += f"{i}. [{err['timestamp']}] {err['container']}: {err['message'][:150]}...\n"
        else:
            prompt_text += "Ошибок не найдено\n"
        
        prompt_text += f"""
АКТИВНЫЕ АЛЕРТЫ:
{alerts}

ЗАДАЧИ:
1. Реконструируй timeline инцидента
2. Определи root cause проблемы
3. Оцени impact на систему
4. Предложи remediation plan
5. Дай рекомендации по предотвращению подобных инцидентов
"""
        return PromptMessage(
            role="user",
            content=TextContent(type="text", text=prompt_text)
        )
    
    else:
        return PromptMessage(
            role="user",
            content=TextContent(type="text", text=f"Unknown prompt: {name}")
        )


# ============================================================================
# СИСТЕМА ПРОАКТИВНЫХ АЛЕРТОВ
# ============================================================================

async def collect_metrics_for_alerts():
    """Собрать текущие метрики для проверки алертов"""
    try:
        metrics = {}
        
        # CPU usage - используем MAX за последнюю минуту, чтобы не пропустить пики
        cpu_max = await prometheus_client.get_cpu_max_last_minutes(1)
        if cpu_max is not None:
            metrics['cpu_usage'] = cpu_max
        else:
            # Fallback на текущее значение, если max недоступен
            cpu_usage = await prometheus_client.get_current_cpu()
            if cpu_usage is not None:
                metrics['cpu_usage'] = cpu_usage
        
        # Memory usage
        memory_data = await prometheus_client.get_current_memory()
        if memory_data:
            metrics['memory_usage'] = memory_data.get('percent', 0)
        
        # Disk usage (берем основной диск /)
        disk_data = await prometheus_client.get_disk_usage()
        if disk_data:
            main_disk = next((d for d in disk_data if d.get('mountpoint') == '/'), None)
            if main_disk:
                metrics['disk_usage'] = main_disk.get('percent', 0)
        
        # Network errors
        network_data = await prometheus_client.get_network_status()
        if network_data:
            errors = network_data.get('errors', {})
            total_errors = errors.get('receive', 0) + errors.get('transmit', 0)
            metrics['network_errors'] = total_errors
        
        return metrics
    
    except Exception as e:
        logger.error(f"Ошибка сбора метрик для алертов: {e}")
        return {}


def can_send_alert(metric_name: str, detection_method: str) -> bool:
    """
    Проверяет, можно ли отправить алерт (cooldown механизм)
    
    Args:
        metric_name: Имя метрики (cpu_usage, memory_usage, etc.)
        detection_method: Тип детекции (zscore, spike, drift)
    
    Returns:
        True если можно отправить, False если еще действует cooldown
    """
    from datetime import datetime, timedelta
    
    cooldown_key = f"{metric_name}_{detection_method}"
    current_time = datetime.now()
    
    # Проверяем есть ли запись в cooldown
    if cooldown_key in alert_cooldown:
        last_sent = alert_cooldown[cooldown_key]
        time_diff = (current_time - last_sent).total_seconds() / 60  # в минутах
        
        if time_diff < ALERT_COOLDOWN_MINUTES:
            # Еще действует cooldown
            return False
    
    # Обновляем время последней отправки
    alert_cooldown[cooldown_key] = current_time
    return True


def aggregate_anomalies(anomalies: list) -> dict:
    """
    Агрегирует аномалии по метрикам для отправки summary вместо множества отдельных алертов
    
    Args:
        anomalies: Список обнаруженных аномалий
    
    Returns:
        Словарь с агрегированными данными по метрикам
    """
    aggregated = {}
    
    for anomaly in anomalies:
        metric = anomaly.metric_name
        if metric not in aggregated:
            aggregated[metric] = {
                'count': 0,
                'max_severity': 'low',
                'detections': [],
                'values': [],
                'highest_anomaly': None
            }
        
        aggregated[metric]['count'] += 1
        aggregated[metric]['detections'].append(anomaly.detection_method)
        aggregated[metric]['values'].append(anomaly.value)
        
        # Обновляем max severity
        severity_order = {'low': 1, 'medium': 2, 'high': 3}
        if severity_order[anomaly.severity] > severity_order[aggregated[metric]['max_severity']]:
            aggregated[metric]['max_severity'] = anomaly.severity
            aggregated[metric]['highest_anomaly'] = anomaly
    
    return aggregated


def should_send_telegram_alert(anomaly) -> bool:
    """
    Определяет, нужно ли отправлять Telegram алерт для данной аномалии
    
    Фильтрует незначительные колебания и применяет более строгие критерии severity.
    """
    metric = anomaly.metric_name
    value = anomaly.value
    severity = anomaly.severity
    
    # ПРАВИЛО 1: Только HIGH severity для критичных метрик
    if severity != 'high':
        logger.debug(f"❌ {metric} severity={severity} (требуется high)")
        return False
    
    # ПРАВИЛО 2: CPU - отправляем при высоком значении или аномальном росте
    if metric == 'cpu_usage':
        # Absolute threshold ВСЕГДА отправляем (> 90%)
        if anomaly.detection_method == 'absolute':
            pass  # Отправляем всегда
        # Для drift/spike отправляем при > 50% (аномальный рост)
        elif anomaly.detection_method in ['drift', 'spike']:
            if value < 50:
                logger.debug(f"❌ CPU {value:.1f}% < 50% для {anomaly.detection_method}")
                return False
        # Для zscore отправляем только при > 70% (абсолютная перегрузка)
        else:  # zscore
            if value < 70:
                logger.debug(f"❌ CPU {value:.1f}% < 70% для zscore")
                return False
    
    # ПРАВИЛО 3: Memory - только если > 80% (или absolute)
    if metric == 'memory_usage':
        if anomaly.detection_method != 'absolute' and value < 80:
            logger.debug(f"❌ Memory {value:.1f}% < 80%")
            return False
    
    # ПРАВИЛО 4: Disk - только если > 85% (или absolute)
    if metric == 'disk_usage':
        if anomaly.detection_method != 'absolute' and value < 85:
            logger.debug(f"❌ Disk {value:.1f}% < 85%")
            return False
    
    # ПРАВИЛО 5: Проверяем cooldown
    if not can_send_alert(metric, anomaly.detection_method):
        logger.debug(f"⏳ Cooldown активен для {metric}_{anomaly.detection_method}, пропускаем алерт")
        return False
    
    logger.info(f"✅ TELEGRAM АЛЕРТ РАЗРЕШЕН: {metric}={value:.1f}% (severity={severity}, method={anomaly.detection_method})")
    return True


async def alert_check_loop():
    """Фоновая задача для периодической проверки метрик и отправки алертов"""
    global alert_manager, anomaly_detector, metric_history
    
    logger.info("🔔 Запуск фоновой проверки алертов (интервал: 60 секунд)")
    logger.info(f"⏰ Cooldown для алертов: {ALERT_COOLDOWN_MINUTES} минут")
    
    while True:
        try:
            # Ждем 60 секунд перед следующей проверкой
            await asyncio.sleep(60)
            
            # Проверяем что AlertManager инициализирован
            if not alert_manager:
                logger.warning("AlertManager не инициализирован, пропускаем проверку")
                continue
            
            # Собираем метрики
            metrics = await collect_metrics_for_alerts()
            
            if not metrics:
                logger.warning("Не удалось собрать метрики, пропускаем проверку")
                continue
            
            # === ДЕТЕКЦИЯ АНОМАЛИЙ ===
            if anomaly_detector:
                detected_anomalies = []
                
                # Обновляем историю и проверяем аномалии для каждой метрики
                for metric_name, current_value in metrics.items():
                    # Добавляем в историю
                    if metric_name not in metric_history:
                        metric_history[metric_name] = []
                    
                    metric_history[metric_name].append(current_value)
                    
                    # Ограничиваем размер истории (последние 100 значений)
                    if len(metric_history[metric_name]) > 100:
                        metric_history[metric_name] = metric_history[metric_name][-100:]
                    
                    # 1. ABSOLUTE THRESHOLD DETECTION (срабатывает СРАЗУ на критичные значения)
                    absolute_anomaly = None
                    if metric_name == 'cpu_usage' and current_value > 90:
                        absolute_anomaly = Anomaly(
                            metric_name='cpu_usage',
                            value=current_value,
                            detection_method='absolute',
                            severity='high',
                            timestamp=datetime.now(),
                            details=f"Absolute threshold exceeded: {current_value:.2f}% > 90%"
                        )
                    elif metric_name == 'memory_usage' and current_value > 90:
                        absolute_anomaly = Anomaly(
                            metric_name='memory_usage',
                            value=current_value,
                            detection_method='absolute',
                            severity='high',
                            timestamp=datetime.now(),
                            details=f"Absolute threshold exceeded: {current_value:.2f}% > 90%"
                        )
                    elif metric_name == 'disk_usage' and current_value > 90:
                        absolute_anomaly = Anomaly(
                            metric_name='disk_usage',
                            value=current_value,
                            detection_method='absolute',
                            severity='high',
                            timestamp=datetime.now(),
                            details=f"Absolute threshold exceeded: {current_value:.2f}% > 90%"
                        )
                    
                    if absolute_anomaly:
                        detected_anomalies.append(absolute_anomaly)
                        logger.warning(f"🚨 ABSOLUTE THRESHOLD: {metric_name}={current_value:.2f}% > 90%")
                    
                    # 2. STATISTICAL ANOMALY DETECTION (требует истории)
                    if len(metric_history[metric_name]) >= anomaly_detector.min_history_size:
                        anomalies = anomaly_detector.detect_anomalies(
                            metric_name=metric_name,
                            current_value=current_value,
                            history=metric_history[metric_name][:-1]  # Исключаем текущее значение из истории
                        )
                        
                        if anomalies:
                            detected_anomalies.extend(anomalies)
                
                # Логируем обнаруженные аномалии
                if detected_anomalies:
                    logger.warning(f"🔍 Детектор аномалий: обнаружено {len(detected_anomalies)} аномалий")
                    for anomaly in detected_anomalies:
                        logger.warning(f"  - {anomaly}")
                    
                    # Фильтруем аномалии для отправки в Telegram
                    anomalies_to_send = [a for a in detected_anomalies if should_send_telegram_alert(a)]
                    
                    if anomalies_to_send and telegram_notifier:
                        logger.info(f"📤 Отправка {len(anomalies_to_send)} критичных алертов в Telegram (из {len(detected_anomalies)} обнаруженных)")
                        
                        # Агрегируем аномалии по метрикам
                        aggregated = aggregate_anomalies(anomalies_to_send)
                        
                        # Отправляем по одному сообщению на метрику
                        for metric_name, data in aggregated.items():
                            try:
                                anomaly = data['highest_anomaly']
                                
                                # Определяем эмодзи для типа метрики
                                metric_emoji = {
                                    'cpu_usage': '💻',
                                    'memory_usage': '🧠',
                                    'disk_usage': '💾',
                                    'network_errors': '🌐'
                                }.get(metric_name, '📊')
                                
                                # Определяем эмодзи для типа детекции
                                detection_emoji = {
                                    'zscore': '📈',
                                    'spike': '⚡',
                                    'drift': '📉'
                                }.get(anomaly.detection_method, '🔍')
                                
                                # Красивое имя метрики
                                metric_name_readable = metric_name.replace('_', ' ').title()
                                
                                # Формируем красивое сообщение
                                detections_str = ", ".join(set(data['detections']))
                                message = (
                                    f"🚨 КРИТИЧНАЯ АНОМАЛИЯ!\n"
                                    f"{'='*35}\n\n"
                                    f"{metric_emoji} МЕТРИКА: {metric_name_readable}\n"
                                    f"{detection_emoji} МЕТОДЫ: {detections_str.upper()}\n"
                                    f"🎯 ТЕКУЩЕЕ ЗНАЧЕНИЕ: {anomaly.value:.2f}%\n"
                                    f"📊 ОБНАРУЖЕНО АНОМАЛИЙ: {data['count']}\n\n"
                                    f"📋 ГЛАВНАЯ АНОМАЛИЯ:\n"
                                    f"{anomaly.details}\n\n"
                                    f"🕐 ВРЕМЯ: {anomaly.timestamp.strftime('%d.%m.%Y %H:%M:%S')}\n"
                                    f"⏰ Следующий алерт через: {ALERT_COOLDOWN_MINUTES} мин\n"
                                    f"{'='*35}"
                                )
                                
                                # Отправляем без parse_mode (без Markdown)
                                success = await telegram_notifier.send_message(message, parse_mode=None)
                                
                                if success:
                                    logger.info(f"✅ Telegram алерт отправлен для {metric_name}")
                                else:
                                    logger.error(f"❌ Не удалось отправить Telegram алерт для {metric_name}")
                            except Exception as e:
                                logger.error(f"❌ Ошибка отправки Telegram алерта для {metric_name}: {e}")
                    else:
                        if detected_anomalies:
                            logger.info(f"⏭️ Все {len(detected_anomalies)} аномалий отфильтрованы (не критичны или cooldown активен)")
            
            # Проверяем алерты (threshold-based)
            new_alerts = await alert_manager.check_alerts(metrics)
            
            if new_alerts:
                logger.info(f"🚨 Обнаружено {len(new_alerts)} новых алертов")
                for alert in new_alerts:
                    logger.warning(f"  - {alert.name}: {alert.message}")
            
        except asyncio.CancelledError:
            logger.info("Фоновая задача проверки алертов остановлена")
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле проверки алертов: {e}")
            # Продолжаем работу даже при ошибке
            await asyncio.sleep(10)


# ============================================================================
# MCP TOOLS
# ============================================================================

@app.list_tools()
async def list_tools() -> list[Tool]:
    """
    Список доступных tools
    """
    return [
        Tool(
            name="get_cpu_usage",
            description="Получить текущую загрузку CPU сервера в процентах. "
                       "Возвращает значение CPU usage и анализ от LLM.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_cpu_usage_raw",
            description="🚀 Быстрая проверка CPU БЕЗ LLM (статистика только)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_memory_status_raw",
            description="🚀 Быстрая проверка памяти БЕЗ LLM (статистика только)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_disk_usage_raw",
            description="🚀 Быстрая проверка дисков БЕЗ LLM (статистика только)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_network_status_raw",
            description="🚀 Быстрая проверка сети БЕЗ LLM (статистика только)",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_top_processes_raw",
            description="🚀 Быстрый список топ процессов БЕЗ LLM (статистика только)",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "number",
                        "description": "Количество процессов (по умолчанию 10)",
                        "default": 10
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_disk_usage",
            description="🎓 Глубокий анализ дисков с AI рекомендациями",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_memory_status",
            description="🎓 Глубокий анализ памяти с AI диагностикой утечек",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="search_error_logs",
            description="Найти ошибки в логах за указанный период времени. "
                       "Возвращает список ошибок с анализом от LLM.",
            inputSchema={
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "number",
                        "description": "Сколько часов назад искать (по умолчанию 1)",
                        "default": 1
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_network_status",
            description="🎓 Глубокий анализ сети с AI диагностикой проблем",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_top_processes",
            description="🎓 Анализ процессов с AI выявлением аномальных процессов",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "number",
                        "description": "Количество процессов для отображения (по умолчанию 10)",
                        "default": 10
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_active_alerts",
            description="Получить активные алерты системы. "
                       "Возвращает список текущих проблем и предупреждений.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="analyze_full_system",
            description="Полный анализ системы: собирает все метрики и анализирует одним вызовом LLM"
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Обработка вызовов tools
    """
    logger.info(f"Вызов tool: {name} с аргументами: {arguments}")
    
    try:
        # === TOOLS С LLM АНАЛИЗОМ ===
        if name == "get_cpu_usage":
            return await tool_get_cpu_usage()
        
        elif name == "get_memory_status":
            return await tool_get_memory_status()
        
        elif name == "get_disk_usage":
            return await tool_get_disk_usage()
        
        elif name == "get_network_status":
            return await tool_get_network_status()
        
        elif name == "get_top_processes":
            limit = arguments.get("limit", 10)
            return await tool_get_top_processes(limit)
        
        elif name == "search_error_logs":
            hours = arguments.get("hours", 1)
            return await tool_search_error_logs(hours)
        
        elif name == "analyze_full_system":
            return await tool_analyze_full_system()
        
        # === RAW TOOLS (БЕЗ LLM) ===
        elif name == "get_cpu_usage_raw":
            return await tool_get_cpu_usage_raw()
        
        elif name == "get_memory_status_raw":
            return await tool_get_memory_status_raw()
        
        elif name == "get_disk_usage_raw":
            return await tool_get_disk_usage_raw()
        
        elif name == "get_network_status_raw":
            return await tool_get_network_status_raw()
        
        elif name == "get_top_processes_raw":
            limit = arguments.get("limit", 10)
            return await tool_get_top_processes_raw(limit)
        
        # === УТИЛИТЫ ===
        elif name == "get_active_alerts":
            return await tool_get_active_alerts()
        
        else:
            logger.error(f"Неизвестный tool: {name}")
            return [TextContent(
                type="text",
                text=f"Ошибка: tool '{name}' не найден"
            )]
    
    except Exception as e:
        logger.exception(f"Ошибка при выполнении tool {name}")
        return [TextContent(
            type="text",
            text=f"Ошибка при выполнении {name}: {str(e)}"
        )]


# ============================================================================
# TOOL IMPLEMENTATIONS
# ============================================================================

async def get_active_alerts() -> str:
    """Получить активные алерты из Prometheus"""
    try:
        import httpx
        
        # Получаем алерты из Prometheus API
        async with httpx.AsyncClient() as client:
            response = await client.get("http://147.45.157.2:9090/api/v1/alerts")
            
            if response.status_code == 200:
                data = response.json()
                alerts = data.get('data', {}).get('alerts', [])
                
                # Фильтруем только активные алерты
                firing_alerts = [alert for alert in alerts if alert.get('state') == 'firing']
                
                if not firing_alerts:
                    return "No active alerts"
                
                result = f"Active Alerts ({len(firing_alerts)}):\n"
                for alert in firing_alerts:
                    name = alert.get('labels', {}).get('alertname', 'Unknown')
                    severity = alert.get('labels', {}).get('severity', 'unknown')
                    value = alert.get('value', 'N/A')
                    
                    # Преобразуем значение из научной нотации
                    if isinstance(value, str) and 'e+' in value:
                        try:
                            value = f"{float(value):.1f}%"
                        except:
                            value = str(value)
                    
                    severity_icon = "🔴" if severity == "critical" else "🟡"
                    result += f"  {severity_icon} {name} (Severity: {severity}, Value: {value})\n"
                
                return result.strip()
            else:
                return f"Ошибка получения алертов: HTTP {response.status_code}"
                
    except Exception as e:
        return f"Ошибка получения алертов: {str(e)}"


async def tool_get_cpu_usage() -> list[TextContent]:
    """Tool: Получение загрузки CPU"""
    
    logger.info("Выполнение get_cpu_usage")
    
    # Получаем данные из Prometheus
    cpu_current = await prometheus_client.get_current_cpu()
    cpu_avg_5m = await prometheus_client.get_cpu_max_last_minutes(5)
    cpu_trend = await prometheus_client.get_cpu_series_5m()
    
    if cpu_current is None:
        return [TextContent(
            type="text",
            text="Ошибка: не удалось получить метрики CPU из Prometheus"
        )]
    
    # Получаем активные алерты
    alerts_text = await get_active_alerts()
    
    # Анализ через LLM со специализированным промптом для CPU
    logger.info(f"CPU: текущий {cpu_current:.2f}%, max за 5мин {cpu_avg_5m:.2f}%, тренд {cpu_trend.get('arrow','→')}, отправка на анализ в DeepSeek...")
    
    analysis = await llm_client.analyze_metrics(
        {
            "cpu_current": cpu_current,
            "cpu_max_5m": cpu_avg_5m,
            "cpu_trend": {"min": cpu_trend.get("min",0), "avg": cpu_trend.get("avg",0), "max": cpu_trend.get("max",0), "direction": cpu_trend.get("direction","flat")},
            "threshold": settings.cpu_threshold,
            "status": "high" if cpu_current > settings.cpu_threshold else "normal",
            "active_alerts": alerts_text
        },
        context="""Глубокий анализ загрузки CPU:
- Оцени текущее состояние CPU (норма/перегрузка/критично)
- Проанализируй тренд за 5 минут (растет/падает/стабильно)
- Если нагрузка высокая (>70%), определи возможные причины (DoS-атака, CPU-интенсивные процессы, утечка в коде, крон-задачи)
- Дай конкретные рекомендации: что проверить в первую очередь, какие команды выполнить (top, htop, ps aux)
- Оцени риски: насколько критична ситуация (0-10), через сколько времени может стать критично
- Учитывай активные алерты Prometheus"""
    )
    
    # Форматирование результата
    result = f"""CPU Usage: {cpu_current:.2f}% (max за 5мин: {cpu_avg_5m:.2f}%)
Threshold: {settings.cpu_threshold}%
Trend(5m): {cpu_trend.get('arrow','→')}  min/avg/max: {cpu_trend.get('min',0):.1f}/{cpu_trend.get('avg',0):.1f}/{cpu_trend.get('max',0):.1f}%
Status: {'⚠️ HIGH' if cpu_current > settings.cpu_threshold else '✓ NORMAL'}

Анализ LLM:
{analysis}
"""
    
    logger.info("get_cpu_usage выполнен успешно")
    
    return [TextContent(type="text", text=result)]


async def tool_get_cpu_usage_raw() -> list[TextContent]:
    """Tool: Получить загрузку CPU БЕЗ LLM анализа"""
    
    logger.info("Выполнение get_cpu_usage_raw")
    
    # Получаем данные из Prometheus
    cpu_current = await prometheus_client.get_current_cpu()
    cpu_avg_5m = await prometheus_client.get_cpu_max_last_minutes(5)
    cpu_trend = await prometheus_client.get_cpu_series_5m()
    
    if cpu_current is None:
        return [TextContent(
            type="text",
            text="Ошибка: не удалось получить метрики CPU из Prometheus"
        )]
    
    # Форматируем результат БЕЗ LLM анализа
    result = f"""CPU Usage: {cpu_current:.2f}% max за 5мин: {cpu_avg_5m:.2f}%
Threshold: {settings.cpu_threshold}
Trend5m: {cpu_trend.get('arrow','→')} min/avg/max: {cpu_trend.get('min',0):.1f}/{cpu_trend.get('avg',0):.1f}/{cpu_trend.get('max',0):.1f}%
Status: {'🔴 HIGH' if cpu_current > settings.cpu_threshold else '✓ NORMAL'}"""
    
    return [TextContent(type="text", text=result)]


async def tool_get_memory_status_raw() -> list[TextContent]:
    """Tool: Получить состояние памяти БЕЗ LLM анализа"""
    
    logger.info("Выполнение get_memory_status_raw")
    
    # Получаем данные из Prometheus
    memory = await prometheus_client.get_current_memory()
    mem_trend = await prometheus_client.get_memory_series_5m()
    
    if memory is None:
        return [TextContent(
            type="text",
            text="Ошибка: не удалось получить метрики памяти из Prometheus"
        )]
    
    # Форматируем результат БЕЗ LLM анализа
    result = f"""Memory Status:
- Total: {memory['total_gb']:.2f} GB
- Used: {memory['used_gb']:.2f} GB
- Available: {memory['available_gb']:.2f} GB
- Usage: {memory['percent']:.2f}%
- Threshold: {settings.memory_threshold}%
- Trend(5m): {mem_trend.get('arrow','→')} min/avg/max: {mem_trend.get('min',0):.1f}/{mem_trend.get('avg',0):.1f}/{mem_trend.get('max',0):.1f}%
- Status: {'🔴 HIGH' if memory['percent'] > settings.memory_threshold else '✓ NORMAL'}"""
    
    return [TextContent(type="text", text=result)]


async def tool_get_disk_usage_raw() -> list[TextContent]:
    """Tool: Получить использование дисков БЕЗ LLM анализа"""
    
    logger.info("Выполнение get_disk_usage_raw")
    
    try:
        if prometheus_client is None:
            logger.error("PrometheusClient не инициализирован")
            return [TextContent(type="text", text="Ошибка: PrometheusClient не инициализирован")]
        
        # Получаем данные из Prometheus
        disks = await prometheus_client.get_disk_usage()
        io_5m = await prometheus_client.get_disk_io_5m()
        
        if not disks:
            return [TextContent(
                type="text",
                text="Ошибка: не удалось получить метрики дисков из Prometheus"
            )]
        
        # Форматирование результата БЕЗ LLM
        result = f"""Disk Usage ({len(disks)} devices):
"""
        for disk in disks:
            status = "🔴 HIGH" if disk['percent'] > settings.disk_threshold else "✓ NORMAL"
            result += f"  {disk['device']}: {disk['percent']:.2f}% ({disk['used_gb']:.2f}GB / {disk['total_gb']:.2f}GB) {status}\n"
        
        # Добавляем IO KPI (MB/s)
        read_mb = (io_5m.get('read',{}).get('avg',0))/ (1024**2)
        write_mb = (io_5m.get('write',{}).get('avg',0))/ (1024**2)
        sat_pct = io_5m.get('saturation',{}).get('avg',0) * 100

        result += f"""
Threshold: {settings.disk_threshold}%
IO(5m avg): R {read_mb:.2f} MB/s | W {write_mb:.2f} MB/s | Saturation ~ {sat_pct:.1f}%"""
        
        logger.info("get_disk_usage_raw выполнен успешно")
        
        return [TextContent(type="text", text=result)]
        
    except Exception as e:
        logger.exception(f"Ошибка в get_disk_usage_raw: {e}")
        return [TextContent(type="text", text=f"Ошибка получения дисков: {e}")]


async def tool_get_network_status_raw() -> list[TextContent]:
    """Tool: Получить статус сети БЕЗ LLM анализа"""
    
    logger.info("Выполнение get_network_status_raw")
    
    try:
        # Получаем данные из Prometheus
        network_data = await prometheus_client.get_network_status()
        net_traffic_5m = await prometheus_client.get_network_traffic_5m()
        net_errors_5m = await prometheus_client.get_network_errors_5m()
        
        # Форматируем результат БЕЗ LLM
        result = "Network Status:\n"
        result += f"Status: {network_data['status'].upper()}\n\n"
        
        # Трафик
        traffic = network_data['traffic']
        result += f"Traffic:\n"
        result += f"  Total interfaces: {traffic['total_interfaces']}\n"
        result += f"  Active interfaces: {traffic['active_interfaces']}\n"
        
        for interface, data in traffic['interfaces'].items():
            rx_gb = data.get('rx_bytes', 0) / (1024**3)
            tx_gb = data.get('tx_bytes', 0) / (1024**3)
            status = "UP" if data.get('up', False) else "DOWN"
            result += f"  {interface}: RX={rx_gb:.2f}GB, TX={tx_gb:.2f}GB [{status}]\n"
        
        # Соединения
        connections = network_data['connections']
        result += f"\nConnections:\n"
        result += f"  TCP established: {connections['tcp_established']}\n"
        result += f"  UDP datagrams: {connections['udp_datagrams']}\n"
        result += f"  Total: {connections['total']}\n"
        
        # Ошибки
        errors = network_data['errors']
        result += f"\nErrors:\n"
        result += f"  RX errors: {errors['rx_errors']}\n"
        result += f"  TX errors: {errors['tx_errors']}\n"
        result += f"  Total errors: {errors['total_errors']}\n"
        
        if errors['interfaces_with_errors']:
            result += f"  Interfaces with errors: {', '.join(errors['interfaces_with_errors'])}\n"

        # KPI 5m (MB/s)
        rx_mb = net_traffic_5m.get('rx',{}).get('avg',0) / (1024**2)
        tx_mb = net_traffic_5m.get('tx',{}).get('avg',0) / (1024**2)
        result += f"\nTraffic(5m avg): RX {rx_mb:.2f} MB/s | TX {tx_mb:.2f} MB/s\n"
        result += f"Errors(5m avg): {net_errors_5m.get('avg',0):.2f}/s"
        
        logger.info("get_network_status_raw выполнен успешно")
        
        return [TextContent(type="text", text=result)]
        
    except Exception as e:
        logger.exception(f"Ошибка в get_network_status_raw: {e}")
        return [TextContent(type="text", text=f"Ошибка получения статуса сети: {e}")]


async def tool_get_top_processes_raw(limit: int = 10) -> list[TextContent]:
    """Tool: Получить топ процессов БЕЗ LLM анализа"""
    
    logger.info(f"Выполнение get_top_processes_raw (limit={limit})")
    
    try:
        # Получаем данные из Prometheus
        cpu_processes = await prometheus_client.get_top_processes_by_cpu(limit)
        memory_processes = await prometheus_client.get_top_processes_by_memory(limit)
        # Топ контейнеров (cAdvisor), если доступно
        try:
            container_cpu_top = await prometheus_client.get_container_top_cpu_5()
        except Exception:
            container_cpu_top = []
        try:
            container_mem_top = await prometheus_client.get_container_top_mem_5()
        except Exception:
            container_mem_top = []
        
        # Форматируем результат БЕЗ LLM
        result = f"Top Processes (limit={limit}):\n\n"
        
        # CPU процессы
        result += "CPU Usage:\n"
        if cpu_processes:
            for process in cpu_processes:
                result += f"  {process['rank']}. {process['name']}: {process['cpu_usage']:.2f}%\n"
        else:
            result += "  No CPU process data available\n"
        
        # Memory процессы
        result += "\nMemory Usage:\n"
        if memory_processes:
            for process in memory_processes:
                result += f"  {process['rank']}. {process['name']}: {process['memory_usage_gb']:.2f}GB ({process['memory_percent']:.1f}%)\n"
        else:
            result += "  No memory process data available\n"
        
        # Контейнеры (если доступны)
        if container_cpu_top or container_mem_top:
            result += "\n\nContainers (cAdvisor):\n"
        if container_cpu_top:
            result += "Top CPU (containers):\n"
            for i, c in enumerate(container_cpu_top[:limit], 1):
                result += f"  {i}. {c.get('name','unknown')}: {c.get('cpu_percent',0):.2f}%\n"
        if container_mem_top:
            result += "\nTop Memory (containers):\n"
            for i, c in enumerate(container_mem_top[:limit], 1):
                result += f"  {i}. {c.get('name','unknown')}: {c.get('memory_gb',0):.2f}GB"
        
        logger.info("get_top_processes_raw выполнен успешно")
        
        return [TextContent(type="text", text=result)]
        
    except Exception as e:
        logger.exception(f"Ошибка в get_top_processes_raw: {e}")
        return [TextContent(type="text", text=f"Ошибка получения топ процессов: {e}")]


async def tool_get_memory_status() -> list[TextContent]:
    """Tool: Получение состояния памяти"""
    
    logger.info("Выполнение get_memory_status")
    
    # Получаем данные из Prometheus
    memory = await prometheus_client.get_current_memory()
    mem_trend = await prometheus_client.get_memory_series_5m()
    
    if memory is None:
        return [TextContent(
            type="text",
            text="Ошибка: не удалось получить метрики памяти из Prometheus"
        )]
    
    # Анализ через LLM со специализированным промптом для Memory
    logger.info(f"Memory: {memory['percent']:.2f}%, отправка на анализ...")
    
    analysis = await llm_client.analyze_metrics(
        {
            **memory,
            "trend_5m": {"min": mem_trend.get("min",0), "avg": mem_trend.get("avg",0), "max": mem_trend.get("max",0), "direction": mem_trend.get("direction","flat")}
        },
        context="""Глубокий анализ использования памяти (Memory):
- Оцени текущий уровень использования RAM (норма/высокий/критичный)
- Проанализируй тренд за 5 минут: есть ли утечка памяти (memory leak)? Растет ли usage постепенно?
- Если usage > 80%, это проблема или нормальное состояние? (Linux кеширует данные в RAM)
- Определи возможные причины высокого usage: утечки в приложениях, слишком мало RAM, кеш файловой системы
- Дай конкретные команды для диагностики: free -h, top, ps aux --sort=-rss, /proc/meminfo
- Рекомендации по оптимизации: очистить кеш (echo 3 > /proc/sys/vm/drop_caches), перезапустить проблемные процессы, добавить swap
- Оцени риск OOM Killer (0-10): через сколько времени система может убить процессы"""
    )
    
    # Форматирование результата
    result = f"""Memory Status:
- Total: {memory['total_gb']:.2f} GB
- Used: {memory['used_gb']:.2f} GB
- Available: {memory['available_gb']:.2f} GB
- Usage: {memory['percent']:.2f}%
- Threshold: {settings.memory_threshold}%
 - Trend(5m): {mem_trend.get('arrow','→')} min/avg/max: {mem_trend.get('min',0):.1f}/{mem_trend.get('avg',0):.1f}/{mem_trend.get('max',0):.1f}%
 - Status: {'⚠️ HIGH' if memory['percent'] > settings.memory_threshold else '✓ NORMAL'}

Анализ LLM:
{analysis}
"""
    
    logger.info("get_memory_status выполнен успешно")
    
    return [TextContent(type="text", text=result)]


async def tool_get_disk_usage() -> list[TextContent]:
    """Tool: Получение использования дисков с LLM анализом"""
    
    logger.info("Выполнение get_disk_usage")
    
    try:
        # Проверяем инициализацию клиента
        if prometheus_client is None:
            logger.error("PrometheusClient не инициализирован")
            return [TextContent(type="text", text="Ошибка: PrometheusClient не инициализирован")]
        
        # Получаем данные из Prometheus
        disks = await prometheus_client.get_disk_usage()
        io_5m = await prometheus_client.get_disk_io_5m()
        
        if not disks:
            return [TextContent(
                type="text",
                text="Ошибка: не удалось получить метрики дисков из Prometheus"
            )]
        
        # Получаем активные алерты
        alerts_text = await get_active_alerts()
        
        # Анализ через LLM со специализированным промптом для Disk
        logger.info(f"Диски: {len(disks)} устройств, отправка на анализ в DeepSeek...")
        
        analysis = await llm_client.analyze_metrics(
            {
                "disks": disks,
                "disk_count": len(disks),
                "max_usage": max(disk['percent'] for disk in disks),
                "threshold": settings.disk_threshold,
                "active_alerts": alerts_text
            },
            context="""Глубокий анализ дискового пространства (Disk Usage):
- Оцени критичность для каждого диска: / (корень), /var/log (логи), /tmp (временные файлы)
- Если usage > 85%, определи что занимает место: логи, кеш, базы данных, бэкапы, old kernels
- Проанализируй IO Saturation: высокая ли нагрузка на диск? Есть ли bottleneck?
- Дай конкретные команды для очистки: du -sh /var/log/*, journalctl --vacuum-size=100M, apt autoremove, docker system prune
- Рекомендации по monitoring: настроить ротацию логов (logrotate), автоочистку /tmp, мониторинг SMART
- Оцени риски (0-10): через сколько дней диск будет заполнен полностью (экстраполяция тренда)
- Учитывай активные алерты Prometheus"""
        )
        
        # Форматирование результата
        result = f"""Disk Usage ({len(disks)} devices):
"""
        for disk in disks:
            status = "⚠️ HIGH" if disk['percent'] > settings.disk_threshold else "✓ NORMAL"
            result += f"  {disk['device']}: {disk['percent']:.2f}% ({disk['used_gb']:.2f}GB / {disk['total_gb']:.2f}GB) {status}\n"
        
        # Добавляем IO KPI (MB/s)
        read_mb = (io_5m.get('read',{}).get('avg',0))/ (1024**2)
        write_mb = (io_5m.get('write',{}).get('avg',0))/ (1024**2)
        sat_pct = io_5m.get('saturation',{}).get('avg',0) * 100

        result += f"""
Threshold: {settings.disk_threshold}%
IO(5m avg): R {read_mb:.2f} MB/s | W {write_mb:.2f} MB/s | Saturation ~ {sat_pct:.1f}%

Анализ LLM:
{analysis}"""
        
        logger.info("get_disk_usage выполнен успешно")
        
        return [TextContent(type="text", text=result)]
        
    except Exception as e:
        logger.exception(f"Ошибка в get_disk_usage: {e}")
        return [TextContent(type="text", text=f"Ошибка получения дисков: {e}")]


async def tool_search_error_logs(hours: int = 1) -> list[TextContent]:
    """Tool: Поиск ошибок в логах"""
    
    logger.info(f"Выполнение search_error_logs за последние {hours}ч")
    
    # Получаем ошибки из Loki
    errors = await loki_client.get_error_logs(hours=hours, limit=20)
    
    if not errors:
        return [TextContent(
            type="text",
            text=f"Ошибок за последние {hours}ч не найдено ✓"
        )]
    
    # Получаем активные алерты
    alerts_text = await get_active_alerts()
    
    # Анализ через LLM
    logger.info(f"Найдено {len(errors)} ошибок, отправка на анализ...")
    
    log_messages = [e['message'] for e in errors[:10]]
    
    analysis = await llm_client.analyze_logs(
        log_messages,
        context=f"Анализ ошибок в логах за последние {hours}ч"
    )
    
    # Форматирование результата
    result = f"""Найдено ошибок: {len(errors)}
Период: последние {hours} час(ов)

Последние 5 ошибок:
"""
    
    for i, err in enumerate(errors[:5], 1):
        result += f"\n{i}. [{err['timestamp']}] {err['container']}\n"
        result += f"   {err['message'][:150]}...\n"
    
    result += f"\nАнализ LLM:\n{analysis}\n"
    
    logger.info("search_error_logs выполнен успешно")
    
    return [TextContent(type="text", text=result)]


async def tool_get_network_status() -> list[TextContent]:
    """Tool: Получение статуса сети"""
    
    logger.info("Выполнение get_network_status")
    
    try:
        # Получаем данные из Prometheus
        network_data = await prometheus_client.get_network_status()
        net_traffic_5m = await prometheus_client.get_network_traffic_5m()
        net_errors_5m = await prometheus_client.get_network_errors_5m()
        
        # Получаем активные алерты
        alerts_text = await get_active_alerts()
        
        # Анализ через LLM со специализированным промптом для Network
        logger.info(f"Сеть: {network_data['status']}, отправка на анализ в DeepSeek...")
        
        analysis = await llm_client.analyze_metrics(
            {
                "network_status": network_data['status'],
                "traffic": network_data['traffic'],
                "connections": network_data['connections'],
                "errors": network_data['errors'],
                "traffic_5m": {"rx_avg_bps": net_traffic_5m.get('rx',{}).get('avg',0), "tx_avg_bps": net_traffic_5m.get('tx',{}).get('avg',0)},
                "errors_5m": {"avg": net_errors_5m.get('avg',0)},
                "active_alerts": alerts_text
            },
            context="""Глубокий анализ сетевого статуса (Network):
- Оцени общее состояние сети: healthy/degraded/critical
- Проанализируй трафик RX/TX: нормальный ли уровень? Есть ли DDoS-атака? Неожиданный всплеск трафика?
- Проверь сетевые ошибки: если errors > 0, определи причины (плохой кабель, переполнение буфера, packet loss)
- Анализ соединений TCP/UDP: много ли ESTABLISHED? Есть ли TIME_WAIT flood? SYN flood?
- Дай команды для диагностики: netstat -an, ss -s, tcpdump, iftop, nload, ethtool
- Рекомендации: проверить firewall rules (iptables -L), rate limiting, увеличить buffers (sysctl net.core.rmem_max)
- Оцени риски (0-10): может ли сеть стать bottleneck? Близка ли к пределу пропускной способности?
- Учитывай активные алерты Prometheus"""
        )
        
        # Форматируем результат
        result = "Network Status:\n"
        result += f"Status: {network_data['status'].upper()}\n\n"
        
        # Трафик
        traffic = network_data['traffic']
        result += f"Traffic:\n"
        result += f"  Total interfaces: {traffic['total_interfaces']}\n"
        result += f"  Active interfaces: {traffic['active_interfaces']}\n"
        
        for interface, data in traffic['interfaces'].items():
            rx_gb = data.get('rx_bytes', 0) / (1024**3)
            tx_gb = data.get('tx_bytes', 0) / (1024**3)
            status = "UP" if data.get('up', False) else "DOWN"
            result += f"  {interface}: RX={rx_gb:.2f}GB, TX={tx_gb:.2f}GB [{status}]\n"
        
        # Соединения
        connections = network_data['connections']
        result += f"\nConnections:\n"
        result += f"  TCP established: {connections['tcp_established']}\n"
        result += f"  UDP datagrams: {connections['udp_datagrams']}\n"
        result += f"  Total: {connections['total']}\n"
        
        # Ошибки
        errors = network_data['errors']
        result += f"\nErrors:\n"
        result += f"  RX errors: {errors['rx_errors']}\n"
        result += f"  TX errors: {errors['tx_errors']}\n"
        result += f"  Total errors: {errors['total_errors']}\n"
        
        if errors['interfaces_with_errors']:
            result += f"  Interfaces with errors: {', '.join(errors['interfaces_with_errors'])}\n"

        # KPI 5m (MB/s)
        rx_mb = net_traffic_5m.get('rx',{}).get('avg',0) / (1024**2)
        tx_mb = net_traffic_5m.get('tx',{}).get('avg',0) / (1024**2)
        result += f"\nTraffic(5m avg): RX {rx_mb:.2f} MB/s | TX {tx_mb:.2f} MB/s\n"
        result += f"Errors(5m avg): {net_errors_5m.get('avg',0):.2f}/s\n"
        
        result += f"\nАнализ LLM:\n{analysis}"
        
        logger.info("get_network_status выполнен успешно")
        
        return [TextContent(type="text", text=result)]
        
    except Exception as e:
        logger.exception(f"Ошибка в get_network_status: {e}")
        return [TextContent(type="text", text=f"Ошибка получения статуса сети: {e}")]


async def tool_get_top_processes(limit: int = 10) -> list[TextContent]:
    """Tool: Получение топ процессов"""
    
    logger.info(f"Выполнение get_top_processes (limit={limit})")
    
    try:
        # Получаем данные из Prometheus
        cpu_processes = await prometheus_client.get_top_processes_by_cpu(limit)
        memory_processes = await prometheus_client.get_top_processes_by_memory(limit)
        # Топ контейнеров (cAdvisor), если доступно
        try:
            container_cpu_top = await prometheus_client.get_container_top_cpu_5()
        except Exception:
            container_cpu_top = []
        try:
            container_mem_top = await prometheus_client.get_container_top_mem_5()
        except Exception:
            container_mem_top = []
        
        # Получаем активные алерты
        alerts_text = await get_active_alerts()
        
        # Анализ через LLM со специализированным промптом для Processes
        logger.info(f"Процессы: CPU={len(cpu_processes)}, Memory={len(memory_processes)}, отправка на анализ...")
        
        analysis = await llm_client.analyze_metrics(
            {
                "cpu_processes": cpu_processes,
                "memory_processes": memory_processes,
                "containers_top_cpu": container_cpu_top,
                "containers_top_mem": container_mem_top,
                "process_count": len(cpu_processes) + len(memory_processes),
                "active_alerts": alerts_text
            },
            context="""Глубокий анализ процессов и контейнеров (Processes):
- Проанализируй топ процессов по CPU: это нормальные системные процессы или аномалии?
- Выяви подозрительные процессы: cryptominers (xmrig, minerd), backdoors, зомби-процессы
- Проверь процессы по Memory: есть ли утечки? Какие процессы растут со временем?
- Для Docker контейнеров: какой контейнер потребляет больше всего? Почему?
- Определи ненужные процессы: что можно safely убить? Что нужно перезапустить?
- Дай команды: kill -9 PID, systemctl restart service, docker restart container
- Рекомендации по оптимизации: ограничить CPU/Memory для контейнеров (--cpus, --memory), настроить nice/ionice
- Оцени (0-10): насколько критично состояние? Есть ли runaway process?
- Учитывай активные алерты Prometheus"""
        )
        
        # Форматируем результат
        result = f"Top Processes (limit={limit}):\n\n"
        
        # CPU процессы
        result += "CPU Usage:\n"
        if cpu_processes:
            for process in cpu_processes:
                result += f"  {process['rank']}. {process['name']}: {process['cpu_usage']:.2f}%\n"
        else:
            result += "  No CPU process data available\n"
        
        # Memory процессы
        result += "\nMemory Usage:\n"
        if memory_processes:
            for process in memory_processes:
                result += f"  {process['rank']}. {process['name']}: {process['memory_usage_gb']:.2f}GB ({process['memory_percent']:.1f}%)\n"
        else:
            result += "  No memory process data available\n"
        
        # Контейнеры (если доступны)
        if container_cpu_top or container_mem_top:
            result += "\n\nContainers (cAdvisor):\n"
        if container_cpu_top:
            result += "Top CPU (containers):\n"
            for i, c in enumerate(container_cpu_top[:limit], 1):
                result += f"  {i}. {c.get('name','unknown')}: {c.get('cpu_percent',0):.2f}%\n"
        if container_mem_top:
            result += "\nTop Memory (containers):\n"
            for i, c in enumerate(container_mem_top[:limit], 1):
                result += f"  {i}. {c.get('name','unknown')}: {c.get('memory_gb',0):.2f}GB\n"

        result += f"\nАнализ LLM:\n{analysis}"
        
        logger.info("get_top_processes выполнен успешно")
        
        return [TextContent(type="text", text=result)]
        
    except Exception as e:
        logger.exception(f"Ошибка в get_top_processes: {e}")
        return [TextContent(type="text", text=f"Ошибка получения топ процессов: {e}")]


async def tool_get_active_alerts() -> list[TextContent]:
    """Tool: Получение активных алертов"""
    
    logger.info("Выполнение get_active_alerts")
    
    try:
        import httpx
        
        # Получаем алерты из Prometheus API
        async with httpx.AsyncClient() as client:
            response = await client.get("http://147.45.157.2:9090/api/v1/alerts")
            
            if response.status_code == 200:
                data = response.json()
                alerts = data.get('data', {}).get('alerts', [])
                
                # Фильтруем только активные алерты
                firing_alerts = [alert for alert in alerts if alert.get('state') == 'firing']
                
                if not firing_alerts:
                    result = "Active Alerts: No active alerts"
                else:
                    result = f"Active Alerts ({len(firing_alerts)}):\n"
                    for alert in firing_alerts:
                        name = alert.get('labels', {}).get('alertname', 'Unknown')
                        severity = alert.get('labels', {}).get('severity', 'unknown')
                        value = alert.get('value', 'N/A')
                        
                        # Преобразуем значение из научной нотации
                        if isinstance(value, str) and 'e+' in value:
                            try:
                                value = f"{float(value):.1f}%"
                            except:
                                value = str(value)
                        
                        severity_icon = "🔴" if severity == "critical" else "🟡"
                        result += f"  {severity_icon} {name} (Severity: {severity}, Value: {value})\n"
                
                logger.info("get_active_alerts выполнен успешно")
                return [TextContent(type="text", text=result)]
            else:
                logger.error(f"Ошибка получения алертов: HTTP {response.status_code}")
                return [TextContent(type="text", text=f"Ошибка получения алертов: HTTP {response.status_code}")]
                
    except Exception as e:
        logger.exception(f"Ошибка в get_active_alerts: {e}")
        return [TextContent(type="text", text=f"Ошибка получения алертов: {e}")]


async def tool_analyze_full_system() -> list[TextContent]:
    """Tool: Полный анализ системы одним вызовом"""
    
    logger.info("Выполнение analyze_full_system")
    
    try:
        # Собираем все данные
        cpu_current = await prometheus_client.get_current_cpu()
        cpu_max_5m = await prometheus_client.get_cpu_max_last_minutes(5)
        cpu_trend = await prometheus_client.get_cpu_trend(5)
        
        memory_data = await prometheus_client.get_current_memory()
        memory_trend = await prometheus_client.get_memory_trend(5)
        
        disk_data = await prometheus_client.get_disk_usage()
        disk_io_trends = await prometheus_client.get_disk_io_trends(5)
        
        network_data = await prometheus_client.get_network_traffic()
        network_connections = await prometheus_client.get_network_connections()
        network_traffic_trends = await prometheus_client.get_network_traffic_trends(5)
        network_error_trends = await prometheus_client.get_network_error_trends(5)
        
        processes_data = await prometheus_client.get_top_processes_by_cpu(5)
        container_cpu_top = await prometheus_client.get_container_cpu_top(5)
        container_mem_top = await prometheus_client.get_container_memory_top(5)
        
        logs = await loki_client.get_error_logs(hours=1, limit=5)
        
        alerts_text = await get_active_alerts()
        
        # Формируем единый словарь для LLM
        metrics_data = {
            "cpu": {"current": cpu_current, "max_5m": cpu_max_5m, "trend": cpu_trend},
            "memory": memory_data, "memory_trend": memory_trend,
            "disks": disk_data, "disk_io": disk_io_trends,
            "network": network_data, "connections": network_connections,
            "network_traffic": network_traffic_trends, "network_errors": network_error_trends,
            "processes": processes_data,
            "containers_cpu": container_cpu_top,
            "containers_mem": container_mem_top,
            "logs": logs,
            "active_alerts": alerts_text
        }
        
        # Один вызов LLM
        analysis = await llm_client.analyze_metrics(
            metrics_data,
            context="Полный анализ системы: все метрики и алерты. Структурируй ответ по секциям (CPU, Память, Диски, Сеть, Процессы, Логи, Алерты)."
        )
        
        return [TextContent(type="text", text=analysis)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Ошибка полного анализа: {e}")]


# HTTP API для Telegram бота
@http_app.post("/call_tool")
async def http_call_tool(request: dict):
    """HTTP endpoint для вызова MCP tools"""
    try:
        tool_name = request.get("tool_name") or request.get("name")
        arguments = request.get("arguments", {})
        
        if not tool_name:
            raise HTTPException(status_code=400, detail="Tool name is required")
        
        # Маппинг tool names на функции
        tool_mapping = {
            # === С LLM АНАЛИЗОМ ===
            "get_cpu_usage": tool_get_cpu_usage,
            "get_memory_status": tool_get_memory_status,
            "get_disk_usage": tool_get_disk_usage,
            "get_network_status": tool_get_network_status,
            "get_top_processes": tool_get_top_processes,
            "search_error_logs": tool_search_error_logs,
            "analyze_full_system": tool_analyze_full_system,
            
            # === RAW (БЕЗ LLM) ===
            "get_cpu_usage_raw": tool_get_cpu_usage_raw,
            "get_memory_status_raw": tool_get_memory_status_raw,
            "get_disk_usage_raw": tool_get_disk_usage_raw,
            "get_network_status_raw": tool_get_network_status_raw,
            "get_top_processes_raw": tool_get_top_processes_raw,
            
            # === УТИЛИТЫ ===
            "get_active_alerts": tool_get_active_alerts,
        }
        
        if tool_name not in tool_mapping:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
        
        # Вызываем tool
        tool_func = tool_mapping[tool_name]
        result = await tool_func(**arguments)
        
        # Возвращаем результат в формате MCP
        return {"content": [{"type": "text", "text": result[0].text}]}
        
    except Exception as e:
        logger.exception(f"Ошибка при вызове tool {tool_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@http_app.get("/health")
async def health_check():
    """Проверка здоровья HTTP API"""
    return {"status": "healthy", "service": "MCP Monitoring API"}


@http_app.get("/resources")
async def http_list_resources():
    """HTTP endpoint для получения списка Resources"""
    try:
        resources = await list_resources()
        return {
            "resources": [
                {
                    "uri": r.uri,
                    "name": r.name,
                    "description": r.description,
                    "mimeType": r.mimeType
                }
                for r in resources
            ]
        }
    except Exception as e:
        logger.exception("Ошибка получения списка resources")
        raise HTTPException(status_code=500, detail=str(e))


@http_app.get("/resource/{uri:path}")
async def http_read_resource(uri: str):
    """HTTP endpoint для чтения Resource по URI"""
    try:
        # Убираем начальный / если есть
        uri = uri.lstrip('/')
        
        # Добавляем monitoring:// если не указан протокол
        if not uri.startswith("monitoring://"):
            uri = f"monitoring://{uri}"
        
        content = await read_resource(uri)
        
        return {
            "uri": uri,
            "content": content
        }
    except Exception as e:
        logger.exception(f"Ошибка чтения resource {uri}")
        raise HTTPException(status_code=500, detail=str(e))


@http_app.get("/prompts")
async def http_list_prompts():
    """HTTP endpoint для получения списка Prompts"""
    try:
        prompts = await list_prompts()
        return {
            "prompts": [
                {
                    "name": p.name,
                    "description": p.description,
                    "arguments": [
                        {
                            "name": arg.name,
                            "description": arg.description,
                            "required": arg.required
                        }
                        for arg in (p.arguments or [])
                    ]
                }
                for p in prompts
            ]
        }
    except Exception as e:
        logger.exception("Ошибка получения списка prompts")
        raise HTTPException(status_code=500, detail=str(e))


@http_app.post("/prompt/{name}")
async def http_get_prompt(name: str, request: dict = None):
    """HTTP endpoint для генерации Prompt с актуальными данными"""
    try:
        arguments = request.get("arguments", {}) if request else {}
        
        prompt_message = await get_prompt(name, arguments)
        
        # Извлекаем role как строку
        role_value = "user"
        if hasattr(prompt_message.role, 'value'):
            role_value = prompt_message.role.value
        elif isinstance(prompt_message.role, str):
            role_value = prompt_message.role
        else:
            role_value = str(prompt_message.role)
        
        return {
            "name": name,
            "role": role_value,
            "content": prompt_message.content,
            "arguments": arguments
        }
    except Exception as e:
        logger.exception(f"Ошибка генерации prompt {name}")
        raise HTTPException(status_code=500, detail=str(e))


# Запуск сервера
async def main():
    """Главная функция запуска сервера"""
    import sys
    
    # Инициализация клиентов
    await init_clients()
    
    # Запуск фоновой задачи проверки алертов
    alert_task = None
    if alert_manager:
        alert_task = asyncio.create_task(alert_check_loop())
        logger.info("✅ Фоновая задача проверки алертов запущена")
    
    # Проверяем аргументы командной строки
    if len(sys.argv) > 1 and sys.argv[1] == "--transport":
        transport = sys.argv[2] if len(sys.argv) > 2 else "stdio"
    else:
        transport = "stdio"
    
    logger.info(f"Запуск MCP сервера с транспортом: {transport}")
    
    try:
        if transport == "http":
            # Запуск HTTP API
            import uvicorn
            logger.info("Запуск HTTP API на порту 8000")
            config = uvicorn.Config(http_app, host="0.0.0.0", port=8000)
            server = uvicorn.Server(config)
            await server.serve()
        else:
            # Запуск stdio сервера
            async with stdio_server() as (read_stream, write_stream):
                await app.run(read_stream, write_stream, app.create_initialization_options())
    finally:
        # Останавливаем фоновую задачу
        if alert_task:
            alert_task.cancel()
            try:
                await alert_task
            except asyncio.CancelledError:
                pass
        
        await cleanup_clients()


if __name__ == "__main__":
    asyncio.run(main())

