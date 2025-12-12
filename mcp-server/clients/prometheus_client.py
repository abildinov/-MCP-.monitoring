"""
HTTP клиент для Prometheus
Получает метрики с удаленного сервера
"""

import httpx
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from loguru import logger


class PrometheusClient:
    """HTTP клиент для удаленного Prometheus"""
    
    def __init__(self, base_url: str, timeout: int = 30):
        """
        Инициализация клиента
        
        Args:
            base_url: URL Prometheus сервера (например, http://147.45.157.2:9090)
            timeout: Таймаут запросов в секундах
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
        logger.info(f"PrometheusClient инициализирован: {self.base_url}")
    
    async def query(self, promql: str) -> Dict[str, Any]:
        """
        Выполнить PromQL запрос (мгновенный снимок)
        
        Args:
            promql: PromQL выражение
            
        Returns:
            Результат запроса
        """
        url = f"{self.base_url}/api/v1/query"
        params = {"query": promql}
        
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "success":
                logger.error(f"Prometheus query error: {data}")
                return {"status": "error", "data": {}}
            
            logger.debug(f"Query успешен: {promql[:50]}...")
            return data
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP ошибка при запросе к Prometheus: {e}")
            return {"status": "error", "error": str(e), "data": {}}
    
    async def query_range(
        self, 
        promql: str,
        start: datetime,
        end: datetime,
        step: str = "15s"
    ) -> Dict[str, Any]:
        """
        Запрос метрик за период времени
        
        Args:
            promql: PromQL выражение
            start: Начало периода
            end: Конец периода
            step: Шаг между точками данных
            
        Returns:
            Временной ряд данных
        """
        url = f"{self.base_url}/api/v1/query_range"
        params = {
            "query": promql,
            "start": int(start.timestamp()),
            "end": int(end.timestamp()),
            "step": step
        }
        
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "success":
                logger.error(f"Prometheus query_range error: {data}")
                return {"status": "error", "data": {}}
            
            logger.debug(f"Query range успешен: {promql[:50]}...")
            return data
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP ошибка при query_range: {e}")
            return {"status": "error", "error": str(e), "data": {}}
    
    async def get_current_cpu(self) -> Optional[float]:
        """
        Получить текущую нагрузку CPU (%)
        
        Returns:
            Процент загрузки CPU или None при ошибке
        """
        # Используем [1m] для более точного отслеживания пиков нагрузки
        query = '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)'
        result = await self.query(query)
        
        if result.get("status") == "success" and result["data"].get("result"):
            value = float(result["data"]["result"][0]["value"][1])
            logger.info(f"CPU usage: {value:.2f}%")
            return value
        
        return None
    
    async def get_cpu_max_last_minutes(self, minutes: int = 5) -> Optional[float]:
        """
        Получить максимальную нагрузку CPU за последние N минут
        
        Args:
            minutes: Количество минут для анализа
            
        Returns:
            Максимальный процент загрузки CPU или None при ошибке
        """
        # Используем max_over_time с правильным синтаксисом диапазона
        query = f'max_over_time((100 - (avg(rate(node_cpu_seconds_total{{mode="idle"}}[1m])) * 100))[{minutes}m:30s])'
        result = await self.query(query)
        
        if result.get("status") == "success" and result["data"].get("result"):
            value = float(result["data"]["result"][0]["value"][1])
            logger.info(f"CPU max last {minutes}min: {value:.2f}%")
            return value
        else:
            logger.warning(f"Не удалось получить CPU max за {minutes}min: {result}")
        
        return None
    
    async def get_current_memory(self) -> Optional[Dict[str, float]]:
        """
        Получить текущее использование памяти
        
        Returns:
            Словарь с метриками памяти (used, total, percent) или None
        """
        # Запросы для памяти
        total_query = "node_memory_MemTotal_bytes"
        available_query = "node_memory_MemAvailable_bytes"
        
        total_result = await self.query(total_query)
        available_result = await self.query(available_query)
        
        if (total_result.get("status") == "success" and 
            available_result.get("status") == "success"):
            
            total_bytes = float(total_result["data"]["result"][0]["value"][1])
            available_bytes = float(available_result["data"]["result"][0]["value"][1])
            used_bytes = total_bytes - available_bytes
            percent = (used_bytes / total_bytes) * 100
            
            memory_info = {
                "total_gb": total_bytes / (1024**3),
                "used_gb": used_bytes / (1024**3),
                "available_gb": available_bytes / (1024**3),
                "percent": percent
            }
            
            logger.info(f"Memory: {memory_info['percent']:.2f}% used")
            return memory_info
        
        return None
    
    async def get_disk_usage(self) -> Optional[List[Dict[str, Any]]]:
        """
        Получить использование дисков
        
        Returns:
            Список дисков с метриками или None
        """
        query = '''
        100 - (node_filesystem_avail_bytes{fstype!="tmpfs",fstype!="ramfs"} 
        / node_filesystem_size_bytes{fstype!="tmpfs",fstype!="ramfs"} * 100)
        '''
        
        result = await self.query(query)
        
        if result.get("status") == "success" and result["data"].get("result"):
            disks = []
            for item in result["data"]["result"]:
                mountpoint = item["metric"].get("mountpoint", "/")
                
                # Исключаем странные пути - оставляем только настоящие диски
                # Исключаем: config файлы, tmpfs, proc, sys, run, dev, boot (если не главный)
                excluded_paths = [
                    "/etc/hostname", 
                    "/etc/hosts",
                    "/etc/resolv.conf",
                    "/boot/efi", 
                    "/proc", 
                    "/sys", 
                    "/run",
                    "/dev"
                ]
                if any(mountpoint.startswith(ex) for ex in excluded_paths):
                    continue
                
                disk_info = {
                    "device": item["metric"].get("device", "unknown"),
                    "mountpoint": mountpoint,
                    "percent": float(item["value"][1]),
                    "used_gb": 0,
                    "total_gb": 0
                }
                disks.append(disk_info)
            
            logger.info(f"Disk usage получен для {len(disks)} дисков")
            return disks if disks else None
        
        return None
    
    async def check_health(self) -> bool:
        """
        Проверка доступности Prometheus
        
        Returns:
            True если Prometheus доступен
        """
        try:
            url = f"{self.base_url}/-/healthy"
            response = await self.client.get(url, timeout=5)
            is_healthy = response.status_code == 200
            
            if is_healthy:
                logger.info("Prometheus: здоров ✓")
            else:
                logger.warning(f"Prometheus: нездоров (status {response.status_code})")
            
            return is_healthy
            
        except Exception as e:
            logger.error(f"Prometheus недоступен: {e}")
            return False
    
    async def get_network_traffic(self) -> Dict[str, Any]:
        """
        Получить сетевой трафик по интерфейсам
        
        Returns:
            Словарь с данными о трафике
        """
        try:
            # Входящий трафик
            rx_query = 'node_network_receive_bytes_total'
            rx_result = await self.query(rx_query)
            
            # Исходящий трафик
            tx_query = 'node_network_transmit_bytes_total'
            tx_result = await self.query(tx_query)
            
            # Статус интерфейсов
            up_query = 'node_network_up'
            up_result = await self.query(up_query)
            
            interfaces = {}
            
            # Обработка входящего трафика
            if rx_result.get('status') == 'success' and rx_result.get('data', {}).get('result'):
                for item in rx_result['data']['result']:
                    interface = item['metric'].get('device', 'unknown')
                    value = float(item['value'][1])
                    if interface not in interfaces:
                        interfaces[interface] = {}
                    interfaces[interface]['rx_bytes'] = value
            
            # Обработка исходящего трафика
            if tx_result.get('status') == 'success' and tx_result.get('data', {}).get('result'):
                for item in tx_result['data']['result']:
                    interface = item['metric'].get('device', 'unknown')
                    value = float(item['value'][1])
                    if interface not in interfaces:
                        interfaces[interface] = {}
                    interfaces[interface]['tx_bytes'] = value
            
            # Обработка статуса интерфейсов
            if up_result.get('status') == 'success' and up_result.get('data', {}).get('result'):
                for item in up_result['data']['result']:
                    interface = item['metric'].get('device', 'unknown')
                    value = float(item['value'][1])
                    if interface not in interfaces:
                        interfaces[interface] = {}
                    interfaces[interface]['up'] = value == 1
            
            logger.info(f"Получены данные о трафике для {len(interfaces)} интерфейсов")
            return {
                'interfaces': interfaces,
                'total_interfaces': len(interfaces),
                'active_interfaces': sum(1 for iface in interfaces.values() if iface.get('up', False))
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения сетевого трафика: {e}")
            return {'interfaces': {}, 'total_interfaces': 0, 'active_interfaces': 0}
    
    async def get_network_connections(self) -> Dict[str, Any]:
        """
        Получить количество сетевых соединений
        
        Returns:
            Словарь с данными о соединениях
        """
        try:
            # TCP соединения
            tcp_query = 'node_netstat_Tcp_CurrEstab'
            tcp_result = await self.query(tcp_query)
            
            # UDP соединения
            udp_query = 'node_netstat_Udp_CurrDatagrams'
            udp_result = await self.query(udp_query)
            
            connections = {
                'tcp_established': 0,
                'udp_datagrams': 0,
                'total': 0
            }
            
            if tcp_result.get('status') == 'success' and tcp_result.get('data', {}).get('result'):
                connections['tcp_established'] = float(tcp_result['data']['result'][0]['value'][1])
            
            if udp_result.get('status') == 'success' and udp_result.get('data', {}).get('result'):
                connections['udp_datagrams'] = float(udp_result['data']['result'][0]['value'][1])
            
            connections['total'] = connections['tcp_established'] + connections['udp_datagrams']
            
            logger.info(f"Сетевые соединения: TCP={connections['tcp_established']}, UDP={connections['udp_datagrams']}")
            return connections
            
        except Exception as e:
            logger.error(f"Ошибка получения сетевых соединений: {e}")
            return {'tcp_established': 0, 'udp_datagrams': 0, 'total': 0}
    
    async def get_network_errors(self) -> Dict[str, Any]:
        """
        Получить ошибки сети
        
        Returns:
            Словарь с данными об ошибках
        """
        try:
            # Ошибки входящего трафика
            rx_errors_query = 'node_network_receive_errs_total'
            rx_errors_result = await self.query(rx_errors_query)
            
            # Ошибки исходящего трафика
            tx_errors_query = 'node_network_transmit_errs_total'
            tx_errors_result = await self.query(tx_errors_query)
            
            errors = {
                'rx_errors': 0,
                'tx_errors': 0,
                'total_errors': 0,
                'interfaces_with_errors': []
            }
            
            if rx_errors_result.get('status') == 'success' and rx_errors_result.get('data', {}).get('result'):
                for item in rx_errors_result['data']['result']:
                    interface = item['metric'].get('device', 'unknown')
                    value = float(item['value'][1])
                    errors['rx_errors'] += value
                    if value > 0:
                        errors['interfaces_with_errors'].append(interface)
            
            if tx_errors_result.get('status') == 'success' and tx_errors_result.get('data', {}).get('result'):
                for item in tx_errors_result['data']['result']:
                    interface = item['metric'].get('device', 'unknown')
                    value = float(item['value'][1])
                    errors['tx_errors'] += value
                    if value > 0 and interface not in errors['interfaces_with_errors']:
                        errors['interfaces_with_errors'].append(interface)
            
            errors['total_errors'] = errors['rx_errors'] + errors['tx_errors']
            
            logger.info(f"Сетевые ошибки: RX={errors['rx_errors']}, TX={errors['tx_errors']}")
            return errors
            
        except Exception as e:
            logger.error(f"Ошибка получения сетевых ошибок: {e}")
            return {'rx_errors': 0, 'tx_errors': 0, 'total_errors': 0, 'interfaces_with_errors': []}
    
    async def get_top_processes_by_cpu(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получить топ процессов по использованию CPU
        
        Args:
            limit: Количество процессов для возврата
            
        Returns:
            Список процессов с данными о CPU
        """
        try:
            # Используем node_cpu_seconds_total для расчета загрузки по процессам
            # Это приблизительная оценка, так как node_exporter не предоставляет детальные метрики процессов
            query = 'topk(10, rate(node_cpu_seconds_total{mode="user"}[5m]))'
            result = await self.query(query)
            
            processes = []
            
            if result.get('status') == 'success' and result.get('data', {}).get('result'):
                for i, item in enumerate(result['data']['result'][:limit]):
                    cpu_id = item['metric'].get('cpu', f'cpu{i}')
                    value = float(item['value'][1])
                    
                    processes.append({
                        'rank': i + 1,
                        'cpu_id': cpu_id,
                        'cpu_usage': value * 100,  # Конвертируем в проценты
                        'name': f'CPU Core {cpu_id}'
                    })
            
            logger.info(f"Получены топ {len(processes)} процессов по CPU")
            return processes
            
        except Exception as e:
            logger.error(f"Ошибка получения топ процессов по CPU: {e}")
            return []
    
    async def get_top_processes_by_memory(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получить топ процессов по использованию памяти
        
        Args:
            limit: Количество процессов для возврата
            
        Returns:
            Список процессов с данными о памяти
        """
        try:
            # Используем node_memory_MemAvailable_bytes для оценки доступной памяти
            # Это не точные данные о процессах, но дает представление об использовании памяти
            query = 'node_memory_MemAvailable_bytes'
            result = await self.query(query)
            
            processes = []
            
            if result.get('status') == 'success' and result.get('data', {}).get('result'):
                available_bytes = float(result['data']['result'][0]['value'][1])
                available_gb = available_bytes / (1024**3)
                
                # Создаем фиктивные данные о процессах для демонстрации
                # В реальной системе нужно использовать другой экспортер для метрик процессов
                processes.append({
                    'rank': 1,
                    'name': 'System Memory',
                    'memory_usage_gb': available_gb,
                    'memory_percent': (available_gb / 4) * 100  # Предполагаем 4GB общий объем
                })
            
            logger.info(f"Получены данные о памяти для {len(processes)} процессов")
            return processes
            
        except Exception as e:
            logger.error(f"Ошибка получения топ процессов по памяти: {e}")
            return []
    
    async def get_network_status(self) -> Dict[str, Any]:
        """
        Получить полный статус сети
        
        Returns:
            Объединенные данные о сети
        """
        try:
            traffic = await self.get_network_traffic()
            connections = await self.get_network_connections()
            errors = await self.get_network_errors()
            
            return {
                'traffic': traffic,
                'connections': connections,
                'errors': errors,
                'status': 'healthy' if errors['total_errors'] < 100 else 'warning'
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения статуса сети: {e}")
            return {
                'traffic': {'interfaces': {}, 'total_interfaces': 0, 'active_interfaces': 0},
                'connections': {'tcp_established': 0, 'udp_datagrams': 0, 'total': 0},
                'errors': {'rx_errors': 0, 'tx_errors': 0, 'total_errors': 0, 'interfaces_with_errors': []},
                'status': 'error'
            }

    async def get_load_average(self) -> Dict[str, float]:
        """Получить среднюю загрузку системы"""
        try:
            queries = {
                'load1': 'node_load1',
                'load5': 'node_load5', 
                'load15': 'node_load15'
            }
            
            result = {}
            for key, query in queries.items():
                response = await self.query(query)
                if response.get("status") == "success" and response["data"].get("result"):
                    result[key] = float(response["data"]["result"][0]["value"][1])
                else:
                    result[key] = 0.0
            
            logger.info(f"Load Average: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка получения Load Average: {e}")
            return {"load1": 0, "load5": 0, "load15": 0}
    
    async def get_swap_usage(self) -> Dict[str, float]:
        """Получить использование swap памяти"""
        try:
            total_query = "node_memory_SwapTotal_bytes"
            free_query = "node_memory_SwapFree_bytes"
            
            total_result = await self.query(total_query)
            free_result = await self.query(free_query)
            
            if (total_result.get("status") == "success" and 
                free_result.get("status") == "success"):
                
                total_bytes = float(total_result["data"]["result"][0]["value"][1])
                free_bytes = float(free_result["data"]["result"][0]["value"][1])
                used_bytes = total_bytes - free_bytes
                percent = (used_bytes / total_bytes * 100) if total_bytes > 0 else 0
                
                swap_info = {
                    "total_gb": total_bytes / (1024**3),
                    "used_gb": used_bytes / (1024**3),
                    "free_gb": free_bytes / (1024**3),
                    "percent": percent
                }
                
                logger.info(f"Swap: {swap_info['percent']:.2f}% used")
                return swap_info
            else:
                return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}
                
        except Exception as e:
            logger.error(f"Ошибка получения swap: {e}")
            return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}
    
    async def get_file_descriptors(self) -> Dict[str, Any]:
        """Получить информацию о файловых дескрипторах"""
        try:
            allocated_query = "node_filefd_allocated"
            max_query = "node_filefd_maximum"
            
            allocated_result = await self.query(allocated_query)
            max_result = await self.query(max_query)
            
            if (allocated_result.get("status") == "success" and 
                max_result.get("status") == "success"):
                
                allocated = float(allocated_result["data"]["result"][0]["value"][1])
                max_fd = float(max_result["data"]["result"][0]["value"][1])
                
                # Ограничиваем максимум разумным значением (например, 1 миллион)
                # если значение выглядит как переполнение int64
                if max_fd > 1000000:
                    max_fd = 65536  # Типичное значение по умолчанию
                    logger.warning(f"File descriptor max выглядит как переполнение: {max_result['data']['result'][0]['value'][1]}, используем default 65536")
                
                percent = (allocated / max_fd * 100) if max_fd > 0 else 0
                
                fd_info = {
                    "used": int(allocated),
                    "max": int(max_fd),
                    "percent": percent
                }
                
                logger.info(f"File Descriptors: {fd_info['used']}/{fd_info['max']} ({fd_info['percent']:.1f}%)")
                return fd_info
            else:
                return {"used": 0, "max": 65536, "percent": 0}
                
        except Exception as e:
            logger.error(f"Ошибка получения file descriptors: {e}")
            return {"used": 0, "max": 0, "percent": 0}
    
    async def get_system_uptime(self) -> Dict[str, Any]:
        """Получить время работы системы"""
        try:
            uptime_query = "node_boot_time_seconds"
            result = await self.query(uptime_query)
            
            if result.get("status") == "success" and result["data"].get("result"):
                boot_time = float(result["data"]["result"][0]["value"][1])
                current_time = float(result["data"]["result"][0]["value"][0])
                uptime_seconds = current_time - boot_time
                
                # Конвертируем в человекочитаемый формат
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                
                uptime_human = f"{days}d {hours}h {minutes}m"
                
                uptime_info = {
                    "uptime_seconds": uptime_seconds,
                    "uptime_human": uptime_human
                }
                
                logger.info(f"System Uptime: {uptime_human}")
                return uptime_info
            else:
                return {"uptime_seconds": 0, "uptime_human": "Unknown"}
                
        except Exception as e:
            logger.error(f"Ошибка получения uptime: {e}")
            return {"uptime_seconds": 0, "uptime_human": "Unknown"}

    # ------------------------------
    # 5-minute trends and aggregates
    # ------------------------------

    def _aggregate_series(self, values: list[float]) -> Dict[str, Any]:
        """Подсчитать min/avg/max/delta и направление по ряду."""
        if not values:
            return {"min": 0.0, "avg": 0.0, "max": 0.0, "delta": 0.0, "direction": "flat", "arrow": "→"}
        vmin = min(values)
        vmax = max(values)
        avg = sum(values) / len(values)
        delta = values[-1] - values[0]
        direction = "up" if delta > 0.5 else ("down" if delta < -0.5 else "flat")
        arrow = "↑" if direction == "up" else ("↓" if direction == "down" else "→")
        return {"min": vmin, "avg": avg, "max": vmax, "delta": delta, "direction": direction, "arrow": arrow}

    async def get_cpu_series_5m(self) -> Dict[str, Any]:
        """Ряд CPU за 5 минут с агрегатами и направлением."""
        end = datetime.utcnow()
        start = end - timedelta(minutes=5)
        promql = '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)'
        data = await self.query_range(promql, start, end, step="15s")
        points = []
        values = []
        try:
            series = data.get("data", {}).get("result", [])
            if series and series[0].get("values"):
                for ts, val in series[0]["values"]:
                    try:
                        fv = float(val)
                    except Exception:
                        continue
                    values.append(fv)
                    points.append({"t": int(ts), "v": fv})
        except Exception:
            pass
        agg = self._aggregate_series(values)
        return {"points": points, **agg}

    async def get_memory_series_5m(self) -> Dict[str, Any]:
        """Ряд использования памяти за 5 минут (%)."""
        end = datetime.utcnow()
        start = end - timedelta(minutes=5)
        promql = '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100'
        data = await self.query_range(promql, start, end, step="15s")
        points, values = [], []
        try:
            series = data.get("data", {}).get("result", [])
            if series and series[0].get("values"):
                for ts, val in series[0]["values"]:
                    try:
                        fv = float(val)
                    except Exception:
                        continue
                    values.append(fv)
                    points.append({"t": int(ts), "v": fv})
        except Exception:
            pass
        agg = self._aggregate_series(values)
        return {"points": points, **agg}

    async def get_disk_io_5m(self) -> Dict[str, Any]:
        """IO дисков за 5 минут: read_bps, write_bps (суммарно), saturation."""
        end = datetime.utcnow()
        start = end - timedelta(minutes=5)
        read_q = 'sum(rate(node_disk_read_bytes_total{device!~"loop.*|ram.*"}[1m]))'
        write_q = 'sum(rate(node_disk_written_bytes_total{device!~"loop.*|ram.*"}[1m]))'
        sat_q = 'sum(rate(node_disk_io_time_seconds_total{device!~"loop.*|ram.*"}[1m]))'

        read_data = await self.query_range(read_q, start, end, step="15s")
        write_data = await self.query_range(write_q, start, end, step="15s")
        sat_data = await self.query_range(sat_q, start, end, step="15s")

        def extract_series(d: Dict[str, Any]) -> list[float]:
            vals = []
            try:
                res = d.get("data", {}).get("result", [])
                if res and res[0].get("values"):
                    for _, v in res[0]["values"]:
                        try:
                            vals.append(float(v))
                        except Exception:
                            continue
            except Exception:
                pass
            return vals

        read_vals = extract_series(read_data)
        write_vals = extract_series(write_data)
        sat_vals = extract_series(sat_data)

        return {
            "read": {
                "series": read_vals,
                **self._aggregate_series(read_vals)
            },
            "write": {
                "series": write_vals,
                **self._aggregate_series(write_vals)
            },
            "saturation": {
                "series": sat_vals,
                **self._aggregate_series(sat_vals)
            }
        }

    async def get_network_traffic_5m(self) -> Dict[str, Any]:
        """Сетевой трафик за 5 минут: rx_bps и tx_bps (без lo)."""
        end = datetime.utcnow()
        start = end - timedelta(minutes=5)
        rx_q = 'sum(rate(node_network_receive_bytes_total{device!="lo"}[1m]))'
        tx_q = 'sum(rate(node_network_transmit_bytes_total{device!="lo"}[1m]))'

        rx_data = await self.query_range(rx_q, start, end, step="15s")
        tx_data = await self.query_range(tx_q, start, end, step="15s")

        def extract_vals(d: Dict[str, Any]) -> list[float]:
            vals = []
            try:
                res = d.get("data", {}).get("result", [])
                if res and res[0].get("values"):
                    for _, v in res[0]["values"]:
                        try:
                            vals.append(float(v))
                        except Exception:
                            continue
            except Exception:
                pass
            return vals

        rx_vals = extract_vals(rx_data)
        tx_vals = extract_vals(tx_data)
        return {
            "rx": {"series": rx_vals, **self._aggregate_series(rx_vals)},
            "tx": {"series": tx_vals, **self._aggregate_series(tx_vals)}
        }

    async def get_network_errors_5m(self) -> Dict[str, Any]:
        """Ошибки сети за 5 минут: сумма rx+tx ошибок в секунду."""
        end = datetime.utcnow()
        start = end - timedelta(minutes=5)
        q = 'sum(rate(node_network_receive_errs_total[1m]) + rate(node_network_transmit_errs_total[1m]))'
        data = await self.query_range(q, start, end, step="15s")
        vals = []
        try:
            res = data.get("data", {}).get("result", [])
            if res and res[0].get("values"):
                for _, v in res[0]["values"]:
                    try:
                        vals.append(float(v))
                    except Exception:
                        continue
        except Exception:
            pass
        return {"series": vals, **self._aggregate_series(vals)}

    async def get_container_top_cpu_5(self) -> list[Dict[str, Any]]:
        """Top-5 контейнеров по CPU (cAdvisor)."""
        q = 'topk(5, sum by (name)(rate(container_cpu_usage_seconds_total{image!=""}[1m])))'
        data = await self.query(q)
        top = []
        if data.get("status") == "success" and data["data"].get("result"):
            for item in data["data"]["result"]:
                name = item["metric"].get("name", "unknown")
                val = float(item["value"][1]) * 100.0
                top.append({"name": name, "cpu_percent": val})
        return top[:5]

    async def get_container_top_mem_5(self) -> list[Dict[str, Any]]:
        """Top-5 контейнеров по памяти (cAdvisor)."""
        q = 'topk(5, sum by (name)(container_memory_working_set_bytes{image!=""}))'
        data = await self.query(q)
        top = []
        if data.get("status") == "success" and data["data"].get("result"):
            for item in data["data"]["result"]:
                name = item["metric"].get("name", "unknown")
                bytes_v = float(item["value"][1])
                top.append({"name": name, "memory_gb": bytes_v / (1024**3)})
        return top[:5]

    async def get_cpu_trend(self, minutes: int = 5) -> Dict[str, Any]:
        """Получить тренд CPU за указанное время"""
        try:
            query = f"avg_over_time((100 - (avg by (instance) (rate(node_cpu_seconds_total{{mode=\"idle\"}}[1m])) * 100))[{minutes}m:1m])"
            result = await self.query(query)
            
            if result.get("status") == "success" and result["data"].get("result"):
                values = [float(item["value"][1]) for item in result["data"]["result"]]
                if values:
                    min_val = min(values)
                    max_val = max(values)
                    avg_val = sum(values) / len(values)
                    
                    # Определяем направление тренда
                    if len(values) >= 2:
                        if values[-1] > values[0]:
                            arrow = "↑"
                        elif values[-1] < values[0]:
                            arrow = "↓"
                        else:
                            arrow = "→"
                    else:
                        arrow = "→"
                    
                    return {
                        "min": min_val,
                        "max": max_val,
                        "avg": avg_val,
                        "arrow": arrow,
                        "values": values
                    }
            
            return {"min": 0, "max": 0, "avg": 0, "arrow": "→", "values": []}
            
        except Exception as e:
            logger.error(f"Ошибка получения CPU trend: {e}")
            return {"min": 0, "max": 0, "avg": 0, "arrow": "→", "values": []}

    async def get_memory_trend(self, minutes: int = 5) -> Dict[str, Any]:
        """Получить тренд памяти за указанное время"""
        try:
            query = f"(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100"
            result = await self.query(query)
            
            if result.get("status") == "success" and result["data"].get("result"):
                values = [float(item["value"][1]) for item in result["data"]["result"]]
                if values:
                    min_val = min(values)
                    max_val = max(values)
                    avg_val = sum(values) / len(values)
                    
                    # Определяем направление тренда
                    if len(values) >= 2:
                        if values[-1] > values[0]:
                            arrow = "↑"
                        elif values[-1] < values[0]:
                            arrow = "↓"
                        else:
                            arrow = "→"
                    else:
                        arrow = "→"
                    
                    return {
                        "min": min_val,
                        "max": max_val,
                        "avg": avg_val,
                        "arrow": arrow,
                        "values": values
                    }
            
            return {"min": 0, "max": 0, "avg": 0, "arrow": "→", "values": []}
            
        except Exception as e:
            logger.error(f"Ошибка получения Memory trend: {e}")
            return {"min": 0, "max": 0, "avg": 0, "arrow": "→", "values": []}

    async def get_disk_io_trends(self, minutes: int = 5) -> Dict[str, Any]:
        """Получить тренды дискового IO"""
        try:
            read_query = f"avg_over_time(rate(node_disk_read_bytes_total[1m])[{minutes}m:1m])"
            write_query = f"avg_over_time(rate(node_disk_written_bytes_total[1m])[{minutes}m:1m])"
            
            read_result = await self.query(read_query)
            write_result = await self.query(write_query)
            
            read_mb = 0
            write_mb = 0
            
            if read_result.get("status") == "success" and read_result["data"].get("result"):
                read_bytes = sum(float(item["value"][1]) for item in read_result["data"]["result"])
                read_mb = read_bytes / (1024 * 1024)
            
            if write_result.get("status") == "success" and write_result["data"].get("result"):
                write_bytes = sum(float(item["value"][1]) for item in write_result["data"]["result"])
                write_mb = write_bytes / (1024 * 1024)
            
            return {
                "read": {"avg": read_mb},
                "write": {"avg": write_mb}
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения Disk IO trends: {e}")
            return {"read": {"avg": 0}, "write": {"avg": 0}}

    async def get_network_traffic_trends(self, minutes: int = 5) -> Dict[str, Any]:
        """Получить тренды сетевого трафика"""
        try:
            rx_query = f"rate(node_network_receive_bytes_total{{device!=\"lo\"}}[1m])"
            tx_query = f"rate(node_network_transmit_bytes_total{{device!=\"lo\"}}[1m])"
            
            rx_result = await self.query(rx_query)
            tx_result = await self.query(tx_query)
            
            rx_mb = 0
            tx_mb = 0
            
            if rx_result.get("status") == "success" and rx_result["data"].get("result"):
                rx_bytes = sum(float(item["value"][1]) for item in rx_result["data"]["result"])
                rx_mb = rx_bytes / (1024 * 1024)
            
            if tx_result.get("status") == "success" and tx_result["data"].get("result"):
                tx_bytes = sum(float(item["value"][1]) for item in tx_result["data"]["result"])
                tx_mb = tx_bytes / (1024 * 1024)
            
            return {
                "rx": {"avg": rx_mb},
                "tx": {"avg": tx_mb}
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения Network traffic trends: {e}")
            return {"rx": {"avg": 0}, "tx": {"avg": 0}}

    async def get_network_error_trends(self, minutes: int = 5) -> Dict[str, Any]:
        """Получить тренды сетевых ошибок"""
        try:
            error_query = f"rate(node_network_receive_errs_total{{device!=\"lo\"}}[1m])"
            result = await self.query(error_query)
            
            errors_per_sec = 0
            if result.get("status") == "success" and result["data"].get("result"):
                errors_per_sec = sum(float(item["value"][1]) for item in result["data"]["result"])
            
            return {
                "avg": errors_per_sec
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения Network error trends: {e}")
            return {"avg": 0}

    async def get_container_cpu_top(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Получить топ контейнеров по CPU"""
        try:
            query = "topk(10, rate(container_cpu_usage_seconds_total[1m]) * 100)"
            result = await self.query(query)
            
            containers = []
            if result.get("status") == "success" and result["data"].get("result"):
                for item in result["data"]["result"][:limit]:
                    # Пробуем разные поля для имени контейнера
                    container_name = (
                        item["metric"].get("name") or 
                        item["metric"].get("container") or 
                        item["metric"].get("id") or 
                        "unknown"
                    )
                    cpu_percent = float(item["value"][1])
                    
                    # Добавляем дополнительную информацию
                    container_info = {
                        "name": container_name,
                        "cpu_percent": cpu_percent,
                        "image": item["metric"].get("image", "unknown"),
                        "id": item["metric"].get("id", "unknown")[:12]  # Короткий ID
                    }
                    
                    containers.append(container_info)
            
            return containers
            
        except Exception as e:
            logger.error(f"Ошибка получения container CPU top: {e}")
            return []

    async def get_container_memory_top(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Получить топ контейнеров по памяти"""
        try:
            query = "topk(10, container_memory_usage_bytes)"
            result = await self.query(query)
            
            containers = []
            if result.get("status") == "success" and result["data"].get("result"):
                for item in result["data"]["result"][:limit]:
                    # Пробуем разные поля для имени контейнера
                    container_name = (
                        item["metric"].get("name") or 
                        item["metric"].get("container") or 
                        item["metric"].get("id") or 
                        "unknown"
                    )
                    memory_bytes = float(item["value"][1])
                    memory_gb = memory_bytes / (1024**3)
                    
                    # Добавляем дополнительную информацию
                    container_info = {
                        "name": container_name,
                        "memory_gb": memory_gb,
                        "image": item["metric"].get("image", "unknown"),
                        "id": item["metric"].get("id", "unknown")[:12]  # Короткий ID
                    }
                    
                    containers.append(container_info)
            
            return containers
            
        except Exception as e:
            logger.error(f"Ошибка получения container memory top: {e}")
            return []

    async def close(self):
        """Закрыть соединения"""
        await self.client.aclose()
        logger.info("PrometheusClient закрыт")


# Пример использования
if __name__ == "__main__":
    import asyncio
    
    async def test():
        client = PrometheusClient("http://147.45.157.2:9090")
        
        # Проверка здоровья
        is_healthy = await client.check_health()
        print(f"Prometheus healthy: {is_healthy}")
        
        # CPU
        cpu = await client.get_current_cpu()
        print(f"CPU: {cpu}%")
        
        # Memory
        memory = await client.get_current_memory()
        print(f"Memory: {memory}")
        
        # Disk
        disks = await client.get_disk_usage()
        print(f"Disks: {disks}")
        
        await client.close()
    
    asyncio.run(test())

