"""
Модуль статистической детекции аномалий
Реализует три метода: Z-score, Spike Detection, Drift Detection
"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class Anomaly:
    """Обнаруженная аномалия"""
    metric_name: str
    value: float
    detection_method: str  # 'zscore', 'spike', 'drift'
    severity: str  # 'low', 'medium', 'high'
    timestamp: datetime
    details: str
    
    def __str__(self):
        return f"[{self.severity.upper()}] {self.metric_name}: {self.detection_method} - {self.details}"


class StatisticalAnomalyDetector:
    """
    Детектор аномалий на основе статистических методов
    
    Методы детекции:
    1. Z-score: обнаружение выбросов на основе стандартного отклонения
    2. Spike Detection: обнаружение резких скачков значений
    3. Drift Detection: обнаружение постепенного дрейфа метрики
    """
    
    def __init__(self, 
                 zscore_threshold: float = 3.0,
                 spike_factor: float = 1.5,
                 drift_threshold: float = 0.15,
                 min_history_size: int = 10):
        """
        Args:
            zscore_threshold: Порог для Z-score (стандартно 3.0)
            spike_factor: Множитель для детекции скачков (1.5 = 150% от среднего)
            drift_threshold: Порог для drift detection (15% изменение)
            min_history_size: Минимальный размер истории для анализа
        """
        self.zscore_threshold = zscore_threshold
        self.spike_factor = spike_factor
        self.drift_threshold = drift_threshold
        self.min_history_size = min_history_size
        
        logger.info(f"StatisticalAnomalyDetector initialized: "
                   f"zscore={zscore_threshold}, spike_factor={spike_factor}, "
                   f"drift_threshold={drift_threshold}")
    
    def detect_zscore(self, metric_name: str, values: List[float], 
                     current_value: float) -> Optional[Anomaly]:
        """
        Z-score аномалия: обнаружение выбросов
        
        Z-score = (x - mean) / std
        Если |Z-score| > threshold, значение считается аномалией
        
        Args:
            metric_name: Имя метрики
            values: История значений метрики
            current_value: Текущее значение
            
        Returns:
            Anomaly если обнаружена, иначе None
        """
        if len(values) < self.min_history_size:
            return None
        
        try:
            values_array = np.array(values)
            mean = np.mean(values_array)
            std = np.std(values_array)
            
            # Избегаем деления на ноль
            if std == 0:
                return None
            
            zscore = abs((current_value - mean) / std)
            
            if zscore > self.zscore_threshold:
                severity = self._calculate_severity_zscore(zscore, metric_name, current_value)
                
                return Anomaly(
                    metric_name=metric_name,
                    value=current_value,
                    detection_method='zscore',
                    severity=severity,
                    timestamp=datetime.now(),
                    details=f"Z-score={zscore:.2f} (threshold={self.zscore_threshold}), "
                           f"current={current_value:.2f}, mean={mean:.2f}, std={std:.2f}"
                )
        
        except Exception as e:
            logger.error(f"Error in detect_zscore for {metric_name}: {e}")
        
        return None
    
    def detect_spike(self, metric_name: str, current_value: float, 
                    window_values: List[float]) -> Optional[Anomaly]:
        """
        Spike Detection: обнаружение резких скачков
        
        Сравнивает текущее значение со средним в окне.
        Если current > mean * spike_factor, это скачок.
        
        Args:
            metric_name: Имя метрики
            current_value: Текущее значение
            window_values: Значения в окне (например, последние 5 точек)
            
        Returns:
            Anomaly если обнаружен скачок, иначе None
        """
        if len(window_values) < 3:
            return None
        
        try:
            window_mean = np.mean(window_values)
            
            # Проверка на резкий скачок вверх
            if current_value > window_mean * self.spike_factor and window_mean > 0:
                spike_ratio = current_value / window_mean
                severity = self._calculate_severity_spike(spike_ratio, metric_name, current_value)
                
                return Anomaly(
                    metric_name=metric_name,
                    value=current_value,
                    detection_method='spike',
                    severity=severity,
                    timestamp=datetime.now(),
                    details=f"Spike detected: {spike_ratio:.2f}x increase "
                           f"(current={current_value:.2f}, window_mean={window_mean:.2f})"
                )
        
        except Exception as e:
            logger.error(f"Error in detect_spike for {metric_name}: {e}")
        
        return None
    
    def detect_drift(self, metric_name: str, values: List[float], 
                    window_size: int = 10) -> Optional[Anomaly]:
        """
        Drift Detection: обнаружение постепенного дрейфа метрики
        
        Сравнивает среднее значение первой половины окна со второй половиной.
        Если изменение > drift_threshold, это дрейф.
        
        Args:
            metric_name: Имя метрики
            values: История значений
            window_size: Размер окна для анализа
            
        Returns:
            Anomaly если обнаружен дрейф, иначе None
        """
        if len(values) < window_size:
            return None
        
        try:
            # Берем последние window_size значений
            recent_values = values[-window_size:]
            
            # Делим на две половины
            half = window_size // 2
            first_half = recent_values[:half]
            second_half = recent_values[half:]
            
            first_mean = np.mean(first_half)
            second_mean = np.mean(second_half)
            
            # Избегаем деления на ноль
            if first_mean == 0:
                return None
            
            # Процентное изменение (с учетом знака для направления)
            signed_change_percent = (second_mean - first_mean) / first_mean
            change_percent = abs(signed_change_percent)
            
            if change_percent > self.drift_threshold:
                direction = "upward" if signed_change_percent > 0 else "downward"
                severity = self._calculate_severity_drift(signed_change_percent, metric_name, second_mean)
                
                return Anomaly(
                    metric_name=metric_name,
                    value=second_mean,
                    detection_method='drift',
                    severity=severity,
                    timestamp=datetime.now(),
                    details=f"Drift detected: {change_percent*100:.1f}% {direction} change "
                           f"(first_half={first_mean:.2f}, second_half={second_mean:.2f})"
                )
        
        except Exception as e:
            logger.error(f"Error in detect_drift for {metric_name}: {e}")
        
        return None
    
    def detect_anomalies(self, metric_name: str, current_value: float, 
                        history: List[float]) -> List[Anomaly]:
        """
        Комплексная детекция аномалий всеми методами
        
        Args:
            metric_name: Имя метрики
            current_value: Текущее значение
            history: История значений метрики
            
        Returns:
            Список обнаруженных аномалий
        """
        anomalies = []
        
        # Z-score detection
        zscore_anomaly = self.detect_zscore(metric_name, history, current_value)
        if zscore_anomaly:
            anomalies.append(zscore_anomaly)
        
        # Spike detection (используем последние 5 точек)
        if len(history) >= 5:
            spike_anomaly = self.detect_spike(metric_name, current_value, history[-5:])
            if spike_anomaly:
                anomalies.append(spike_anomaly)
        
        # Drift detection
        drift_anomaly = self.detect_drift(metric_name, history + [current_value])
        if drift_anomaly:
            anomalies.append(drift_anomaly)
        
        if anomalies:
            logger.warning(f"Detected {len(anomalies)} anomalies for {metric_name}")
            for anomaly in anomalies:
                logger.debug(f"  - {anomaly}")
        
        return anomalies
    
    def _calculate_severity_zscore(self, zscore: float, metric_name: str = None, value: float = None) -> str:
        """
        Определяет severity на основе Z-score И абсолютного значения метрики
        
        Учитывает, что высокий Z-score на низких значениях не критичен.
        Например, CPU 8% с Z-score=6 - это не критично.
        """
        # Базовая severity по Z-score
        if zscore > 6.0:
            base_severity = 'high'
        elif zscore > 5.0:
            base_severity = 'medium'
        else:
            base_severity = 'low'
        
        # Корректируем severity по абсолютному значению метрики
        if metric_name and value is not None:
            if metric_name == 'cpu_usage':
                if value < 50:  # CPU < 50% - не критично
                    if base_severity == 'high':
                        base_severity = 'medium'
                    elif base_severity == 'medium':
                        base_severity = 'low'
            elif metric_name == 'memory_usage':
                if value < 70:  # Memory < 70% - не критично
                    if base_severity == 'high':
                        base_severity = 'medium'
            elif metric_name == 'disk_usage':
                if value < 80:  # Disk < 80% - не критично
                    if base_severity == 'high':
                        base_severity = 'medium'
        
        return base_severity
    
    def _calculate_severity_spike(self, spike_ratio: float, metric_name: str = None, value: float = None) -> str:
        """
        Определяет severity на основе spike ratio И абсолютного значения
        """
        # Базовая severity по spike ratio
        if spike_ratio > 3.0:
            base_severity = 'high'
        elif spike_ratio > 2.0:
            base_severity = 'medium'
        else:
            base_severity = 'low'
        
        # ВАЖНО: Spike до критичных значений = HIGH severity
        if metric_name and value is not None:
            if metric_name == 'cpu_usage':
                if value > 90:  # CPU spike до > 90% всегда критично
                    base_severity = 'high'
                elif value < 50:  # Spike на низком CPU - не критично
                    if base_severity == 'high':
                        base_severity = 'medium'
            elif metric_name == 'memory_usage':
                if value > 85:
                    base_severity = 'high'
                elif value < 70:
                    if base_severity == 'high':
                        base_severity = 'medium'
        
        return base_severity
    
    def _calculate_severity_drift(self, change_percent: float, metric_name: str = None, value: float = None) -> str:
        """
        Определяет severity на основе процента изменения И абсолютного значения метрики
        """
        # Базовая severity по проценту изменения
        abs_change = abs(change_percent)
        if abs_change > 1.0:  # 100% изменение
            base_severity = 'high'
        elif abs_change > 0.7:  # 70% изменение
            base_severity = 'medium'
        else:
            base_severity = 'low'
        
        # Дрейф вниз менее критичен, чем вверх
        if change_percent < 0 and base_severity == 'high':
            base_severity = 'medium'
        
        # ВАЖНО: учитываем абсолютное значение метрики!
        # Drift вверх до высоких значений = HIGH severity
        if metric_name and value is not None and change_percent > 0:
            if metric_name == 'cpu_usage' and value > 80:
                base_severity = 'high'  # CPU дрейфует к перегрузке
            elif metric_name == 'memory_usage' and value > 85:
                base_severity = 'high'  # Memory дрейфует к переполнению
            elif metric_name == 'disk_usage' and value > 90:
                base_severity = 'high'  # Disk дрейфует к заполнению
        
        return base_severity
    
    def analyze_metric_trends(self, metric_name: str, 
                             values: List[float]) -> Dict[str, any]:
        """
        Анализ трендов метрики
        
        Returns:
            Словарь с статистикой: mean, std, trend_direction, volatility
        """
        if len(values) < 2:
            return {}
        
        try:
            values_array = np.array(values)
            
            # Базовая статистика
            mean_val = np.mean(values_array)
            std_val = np.std(values_array)
            min_val = np.min(values_array)
            max_val = np.max(values_array)
            
            # Определение тренда (линейная регрессия)
            x = np.arange(len(values))
            coeffs = np.polyfit(x, values_array, 1)
            slope = coeffs[0]
            
            if slope > 0.01:
                trend_direction = 'increasing'
            elif slope < -0.01:
                trend_direction = 'decreasing'
            else:
                trend_direction = 'stable'
            
            # Волатильность (коэффициент вариации)
            volatility = (std_val / mean_val * 100) if mean_val != 0 else 0
            
            return {
                'metric_name': metric_name,
                'mean': mean_val,
                'std': std_val,
                'min': min_val,
                'max': max_val,
                'trend_direction': trend_direction,
                'trend_slope': slope,
                'volatility_percent': volatility,
                'data_points': len(values)
            }
        
        except Exception as e:
            logger.error(f"Error in analyze_metric_trends for {metric_name}: {e}")
            return {}

