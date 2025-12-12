"""
Менеджер алертов для системы мониторинга
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from loguru import logger


@dataclass
class Alert:
    """Класс для представления алерта"""
    id: str
    name: str
    severity: str  # 'critical', 'warning', 'info'
    message: str
    metric_name: str
    current_value: float
    threshold: float
    timestamp: datetime
    resolved: bool = False
    resolved_at: Optional[datetime] = None


class AlertRule:
    """Правило для генерации алертов"""
    
    def __init__(
        self,
        name: str,
        metric_name: str,
        threshold: float,
        operator: str = ">",
        severity: str = "warning",
        cooldown_minutes: int = 5
    ):
        self.name = name
        self.metric_name = metric_name
        self.threshold = threshold
        self.operator = operator  # ">", "<", ">=", "<=", "==", "!="
        self.severity = severity
        self.cooldown_minutes = cooldown_minutes
        self.last_alert_time: Optional[datetime] = None
    
    def check_condition(self, value: float) -> bool:
        """Проверить условие алерта"""
        if self.operator == ">":
            return value > self.threshold
        elif self.operator == "<":
            return value < self.threshold
        elif self.operator == ">=":
            return value >= self.threshold
        elif self.operator == "<=":
            return value <= self.threshold
        elif self.operator == "==":
            return value == self.threshold
        elif self.operator == "!=":
            return value != self.threshold
        return False
    
    def can_send_alert(self) -> bool:
        """Проверить, можно ли отправить алерт (с учетом cooldown)"""
        if self.last_alert_time is None:
            return True
        
        cooldown_end = self.last_alert_time + timedelta(minutes=self.cooldown_minutes)
        return datetime.now() > cooldown_end


class AlertManager:
    """Менеджер алертов"""
    
    def __init__(self):
        self.rules: List[AlertRule] = []
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: List[Alert] = []
        self.notifiers = []
        
        # Инициализация правил по умолчанию
        self._init_default_rules()
    
    def _init_default_rules(self):
        """Инициализация правил алертов по умолчанию"""
        default_rules = [
            AlertRule(
                name="High CPU Usage",
                metric_name="cpu_usage",
                threshold=80.0,
                operator=">",
                severity="warning",
                cooldown_minutes=5
            ),
            AlertRule(
                name="Critical CPU Usage",
                metric_name="cpu_usage",
                threshold=95.0,
                operator=">",
                severity="critical",
                cooldown_minutes=2
            ),
            AlertRule(
                name="High Memory Usage",
                metric_name="memory_usage",
                threshold=85.0,
                operator=">",
                severity="warning",
                cooldown_minutes=5
            ),
            AlertRule(
                name="Critical Memory Usage",
                metric_name="memory_usage",
                threshold=95.0,
                operator=">",
                severity="critical",
                cooldown_minutes=2
            ),
            AlertRule(
                name="High Disk Usage",
                metric_name="disk_usage",
                threshold=90.0,
                operator=">",
                severity="warning",
                cooldown_minutes=10
            ),
            AlertRule(
                name="Network Errors",
                metric_name="network_errors",
                threshold=100.0,
                operator=">",
                severity="warning",
                cooldown_minutes=5
            )
        ]
        
        self.rules.extend(default_rules)
        logger.info(f"Инициализировано {len(default_rules)} правил алертов")
    
    def add_rule(self, rule: AlertRule):
        """Добавить новое правило алерта"""
        self.rules.append(rule)
        logger.info(f"Добавлено правило алерта: {rule.name}")
    
    def add_notifier(self, notifier):
        """Добавить уведомитель"""
        self.notifiers.append(notifier)
        logger.info(f"Добавлен уведомитель: {type(notifier).__name__}")
    
    async def check_alerts(self, metrics: Dict[str, Any]) -> List[Alert]:
        """Проверить метрики на превышение порогов"""
        new_alerts = []
        
        for rule in self.rules:
            metric_value = metrics.get(rule.metric_name)
            
            if metric_value is None:
                continue
            
            # Проверяем условие алерта
            if rule.check_condition(metric_value):
                # Проверяем cooldown
                if not rule.can_send_alert():
                    continue
                
                # Создаем алерт
                alert_id = f"{rule.metric_name}_{rule.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                
                alert = Alert(
                    id=alert_id,
                    name=rule.name,
                    severity=rule.severity,
                    message=f"{rule.name}: {metric_value:.2f} {rule.operator} {rule.threshold}",
                    metric_name=rule.metric_name,
                    current_value=metric_value,
                    threshold=rule.threshold,
                    timestamp=datetime.now()
                )
                
                # Добавляем в активные алерты
                self.active_alerts[alert_id] = alert
                new_alerts.append(alert)
                
                # Обновляем время последнего алерта
                rule.last_alert_time = datetime.now()
                
                logger.warning(f"Создан алерт: {alert.name} - {alert.message}")
            
            else:
                # Проверяем, есть ли активный алерт для этого правила
                active_alert = self._find_active_alert_for_rule(rule)
                if active_alert:
                    # Алерт разрешен
                    active_alert.resolved = True
                    active_alert.resolved_at = datetime.now()
                    
                    # Перемещаем в историю
                    self.alert_history.append(active_alert)
                    del self.active_alerts[active_alert.id]
                    
                    logger.info(f"Алерт разрешен: {active_alert.name}")
        
        # Отправляем новые алерты через уведомители
        for alert in new_alerts:
            await self._send_alert(alert)
        
        return new_alerts
    
    def _find_active_alert_for_rule(self, rule: AlertRule) -> Optional[Alert]:
        """Найти активный алерт для правила"""
        for alert in self.active_alerts.values():
            if alert.metric_name == rule.metric_name and alert.name == rule.name:
                return alert
        return None
    
    async def _send_alert(self, alert: Alert):
        """Отправить алерт через все уведомители"""
        for notifier in self.notifiers:
            try:
                await notifier.send_alert(alert)
            except Exception as e:
                logger.error(f"Ошибка отправки алерта через {type(notifier).__name__}: {e}")
    
    def get_active_alerts(self) -> List[Alert]:
        """Получить список активных алертов"""
        return list(self.active_alerts.values())
    
    def get_alert_history(self, hours: int = 24) -> List[Alert]:
        """Получить историю алертов за указанное количество часов"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        return [
            alert for alert in self.alert_history
            if alert.timestamp >= cutoff_time
        ]
    
    def get_alerts_by_severity(self, severity: str) -> List[Alert]:
        """Получить алерты по уровню критичности"""
        return [
            alert for alert in self.active_alerts.values()
            if alert.severity == severity
        ]
    
    def resolve_alert(self, alert_id: str) -> bool:
        """Разрешить алерт по ID"""
        if alert_id in self.active_alerts:
            alert = self.active_alerts[alert_id]
            alert.resolved = True
            alert.resolved_at = datetime.now()
            
            # Перемещаем в историю
            self.alert_history.append(alert)
            del self.active_alerts[alert_id]
            
            logger.info(f"Алерт разрешен вручную: {alert.name}")
            return True
        
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику алертов"""
        active_count = len(self.active_alerts)
        history_count = len(self.alert_history)
        
        severity_counts = {}
        for alert in self.active_alerts.values():
            severity_counts[alert.severity] = severity_counts.get(alert.severity, 0) + 1
        
        return {
            'active_alerts': active_count,
            'total_history': history_count,
            'severity_breakdown': severity_counts,
            'rules_count': len(self.rules),
            'notifiers_count': len(self.notifiers)
        }
