"""
Data collector for gathering metrics over a time period
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List
from loguru import logger

import sys
from pathlib import Path

# Добавляем путь к mcp-server для импортов
mcp_server_path = Path(__file__).parent.parent
if str(mcp_server_path) not in sys.path:
    sys.path.insert(0, str(mcp_server_path))

from clients.prometheus_client import PrometheusClient
from clients.loki_client import LokiClient


async def collect_metrics_for_period(
    period: str,
    prometheus_url: str = "http://147.45.157.2:9090",
    loki_url: str = "http://147.45.157.2:3100"
) -> Dict[str, Any]:
    """
    Собирает метрики за указанный период
    
    Args:
        period: Период в формате "24h", "7d", "30d"
        prometheus_url: URL Prometheus сервера
        loki_url: URL Loki сервера
        
    Returns:
        Словарь с метриками за период
    """
    logger.info(f"Сбор метрик за период: {period}")
    
    # Парсим период
    period_hours = parse_period_to_hours(period)
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=period_hours)
    
    # Инициализируем клиенты
    prom_client = PrometheusClient(prometheus_url)
    loki_client = LokiClient(loki_url)
    
    try:
        # Собираем данные параллельно
        cpu_data = await collect_cpu_metrics(prom_client, start_time, end_time)
        memory_data = await collect_memory_metrics(prom_client, start_time, end_time)
        disk_data = await collect_disk_metrics(prom_client, start_time, end_time)
        network_data = await collect_network_metrics(prom_client, start_time, end_time)
        alerts_data = await collect_alerts(prom_client, start_time, end_time)
        errors_data = await collect_errors(loki_client, period_hours)
        processes_data = await collect_top_processes(prom_client)
        
        result = {
            "period": period,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "cpu": cpu_data,
            "memory": memory_data,
            "disk": disk_data,
            "network": network_data,
            "alerts": alerts_data,
            "errors": errors_data,
            "processes": processes_data
        }
        
        logger.info("Сбор метрик завершен успешно")
        return result
        
    finally:
        await prom_client.close()
        await loki_client.close()


def parse_period_to_hours(period: str) -> int:
    """Конвертирует период в часы"""
    if period.endswith('h'):
        return int(period[:-1])
    elif period.endswith('d'):
        return int(period[:-1]) * 24
    elif period.endswith('w'):
        return int(period[:-1]) * 24 * 7
    else:
        return 24  # По умолчанию сутки


async def collect_cpu_metrics(
    client: PrometheusClient,
    start: datetime,
    end: datetime
) -> Dict[str, Any]:
    """Собирает метрики CPU за период"""
    logger.debug("Сбор CPU метрик")
    
    # Запрос для получения CPU usage за период
    query = '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'
    result = await client.query_range(query, start, end, step="5m")
    
    values = []
    timestamps = []
    if result.get("status") == "success" and result["data"].get("result"):
        for item in result["data"]["result"]:
            if "values" in item:
                for timestamp, value in item["values"]:
                    timestamps.append(datetime.fromtimestamp(timestamp))
                    values.append(float(value))
    
    if values:
        # Вычисляем статистику
        sorted_values = sorted(values)
        median = sorted_values[len(sorted_values) // 2]
        p95 = sorted_values[int(len(sorted_values) * 0.95)] if len(sorted_values) > 1 else sorted_values[0]
        
        # Определяем тренд (первая половина vs вторая половина)
        mid = len(values) // 2
        first_half_avg = sum(values[:mid]) / mid if mid > 0 else 0
        second_half_avg = sum(values[mid:]) / (len(values) - mid) if len(values) > mid else 0
        trend = "↗ Растёт" if second_half_avg > first_half_avg * 1.1 else "↘ Падает" if second_half_avg < first_half_avg * 0.9 else "→ Стабильно"
        
        return {
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "median": median,
            "p95": p95,
            "current": values[-1] if values else 0,
            "samples": len(values),
            "trend": trend,
            "values": values,
            "timestamps": timestamps
        }
    
    return {"min": 0, "max": 0, "avg": 0, "median": 0, "p95": 0, "current": 0, "samples": 0, "trend": "N/A", "values": [], "timestamps": []}


async def collect_memory_metrics(
    client: PrometheusClient,
    start: datetime,
    end: datetime
) -> Dict[str, Any]:
    """Собирает метрики памяти за период"""
    logger.debug("Сбор Memory метрик")
    
    query = '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100'
    result = await client.query_range(query, start, end, step="5m")
    
    values = []
    timestamps = []
    if result.get("status") == "success" and result["data"].get("result"):
        for item in result["data"]["result"]:
            if "values" in item:
                for timestamp, value in item["values"]:
                    timestamps.append(datetime.fromtimestamp(timestamp))
                    values.append(float(value))
    
    # Получаем текущий размер памяти
    memory_info = await client.get_current_memory()
    
    if values:
        # Вычисляем статистику
        sorted_values = sorted(values)
        median = sorted_values[len(sorted_values) // 2]
        p95 = sorted_values[int(len(sorted_values) * 0.95)] if len(sorted_values) > 1 else sorted_values[0]
        
        # Тренд
        mid = len(values) // 2
        first_half_avg = sum(values[:mid]) / mid if mid > 0 else 0
        second_half_avg = sum(values[mid:]) / (len(values) - mid) if len(values) > mid else 0
        trend = "↗ Растёт" if second_half_avg > first_half_avg * 1.1 else "↘ Падает" if second_half_avg < first_half_avg * 0.9 else "→ Стабильно"
        
        return {
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "median": median,
            "p95": p95,
            "current": values[-1] if values else 0,
            "total_gb": memory_info.get("total_gb", 0) if memory_info else 0,
            "samples": len(values),
            "trend": trend,
            "values": values,
            "timestamps": timestamps
        }
    
    return {"min": 0, "max": 0, "avg": 0, "median": 0, "p95": 0, "current": 0, "total_gb": 0, "samples": 0, "trend": "N/A", "values": [], "timestamps": []}


async def collect_disk_metrics(
    client: PrometheusClient,
    start: datetime,
    end: datetime
) -> Dict[str, Any]:
    """Собирает метрики дисков за период"""
    logger.debug("Сбор Disk метрик")
    
    # Текущее использование дисков
    disks = await client.get_disk_usage()
    
    # IO статистика за период
    io_data = await client.get_disk_io_5m()
    
    return {
        "disks": disks or [],
        "io_read_avg_mb": io_data.get("read", {}).get("avg", 0) / (1024**2) if io_data else 0,
        "io_write_avg_mb": io_data.get("write", {}).get("avg", 0) / (1024**2) if io_data else 0
    }


async def collect_network_metrics(
    client: PrometheusClient,
    start: datetime,
    end: datetime
) -> Dict[str, Any]:
    """Собирает сетевые метрики за период"""
    logger.debug("Сбор Network метрик")
    
    # Текущий статус сети
    network_status = await client.get_network_status()
    
    # Трафик за период
    traffic_5m = await client.get_network_traffic_5m()
    errors_5m = await client.get_network_errors_5m()
    
    return {
        "status": network_status.get("status", "unknown"),
        "interfaces": network_status.get("traffic", {}).get("total_interfaces", 0),
        "rx_avg_mb": traffic_5m.get("rx", {}).get("avg", 0) / (1024**2) if traffic_5m else 0,
        "tx_avg_mb": traffic_5m.get("tx", {}).get("avg", 0) / (1024**2) if traffic_5m else 0,
        "errors_avg": errors_5m.get("avg", 0) if errors_5m else 0,
        "connections": network_status.get("connections", {})
    }


async def collect_alerts(
    client: PrometheusClient,
    start: datetime,
    end: datetime
) -> List[Dict[str, Any]]:
    """Собирает информацию об алертах за период"""
    logger.debug("Сбор Alerts за период")
    
    import httpx
    
    try:
        # Получаем исторические данные о срабатывании алертов за период
        # ALERTS - специальная метрика Prometheus которая хранит состояния алертов
        query = 'ALERTS{alertstate="firing"}'
        
        # Формируем запрос к Prometheus query_range API
        params = {
            'query': query,
            'start': start.timestamp(),
            'end': end.timestamp(),
            'step': '5m'  # Проверяем каждые 5 минут
        }
        
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.get(
                "http://147.45.157.2:9090/api/v1/query_range",
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('data', {}).get('result', [])
                
                # Собираем уникальные алерты
                alerts_dict = {}
                
                for result in results:
                    metric = result.get('metric', {})
                    values = result.get('values', [])
                    
                    if values:  # Если были срабатывания за период
                        alertname = metric.get('alertname', 'Unknown')
                        severity = metric.get('severity', 'unknown')
                        
                        # Считаем количество срабатываний
                        firing_count = len(values)
                        
                        # Первое и последнее срабатывание
                        first_time = datetime.fromtimestamp(values[0][0]) if values else None
                        last_time = datetime.fromtimestamp(values[-1][0]) if values else None
                        
                        if alertname not in alerts_dict:
                            alerts_dict[alertname] = {
                                "name": alertname,
                                "severity": severity,
                                "firing_count": firing_count,
                                "first_fired": first_time.strftime('%Y-%m-%d %H:%M:%S') if first_time else 'N/A',
                                "last_fired": last_time.strftime('%Y-%m-%d %H:%M:%S') if last_time else 'N/A',
                                "state": "fired_in_period"
                            }
                        else:
                            # Если уже есть - обновляем счётчик
                            alerts_dict[alertname]["firing_count"] += firing_count
                
                # Также получаем текущие активные алерты
                current_response = await http_client.get("http://147.45.157.2:9090/api/v1/alerts")
                if current_response.status_code == 200:
                    current_data = current_response.json()
                    current_alerts = current_data.get('data', {}).get('alerts', [])
                    
                    for alert in current_alerts:
                        if alert.get('state') == 'firing':
                            alertname = alert.get('labels', {}).get('alertname', 'Unknown')
                            if alertname not in alerts_dict:
                                alerts_dict[alertname] = {
                                    "name": alertname,
                                    "severity": alert.get('labels', {}).get('severity', 'unknown'),
                                    "firing_count": 1,
                                    "first_fired": "Currently firing",
                                    "last_fired": "Currently firing",
                                    "state": "firing_now"
                                }
                            else:
                                alerts_dict[alertname]["state"] = "firing_now"
                
                return list(alerts_dict.values())
                
    except Exception as e:
        logger.error(f"Ошибка получения алертов: {e}", exc_info=True)
    
    return []


async def collect_errors(
    client: LokiClient,
    hours: int
) -> List[Dict[str, str]]:
    """Собирает ошибки из логов за период"""
    logger.debug(f"Сбор Errors за {hours} часов")
    
    errors = await client.get_error_logs(hours=hours, limit=50)
    return errors or []


async def collect_top_processes(client: PrometheusClient) -> List[Dict[str, Any]]:
    """Собирает топ процессов"""
    logger.debug("Сбор Top Processes")
    
    cpu_processes = await client.get_top_processes_by_cpu(10)
    return cpu_processes or []

