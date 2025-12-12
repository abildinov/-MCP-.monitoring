"""
Chart generator for PDF reports
"""

import matplotlib
matplotlib.use('Agg')  # Не требует X11/GUI
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import List, Dict, Any
from loguru import logger


def create_cpu_chart(timestamps: List[datetime], values: List[float], output_path: str) -> str:
    """
    Создаёт линейный график использования CPU
    
    Args:
        timestamps: Список временных меток
        values: Список значений CPU (%)
        output_path: Путь для сохранения графика
        
    Returns:
        Путь к созданному файлу
    """
    logger.debug(f"Создание CPU графика: {len(values)} точек")
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Определяем цвета по зонам
    colors = []
    for value in values:
        if value >= 80:
            colors.append('#FF4444')  # Красный - critical
        elif value >= 60:
            colors.append('#FFA500')  # Оранжевый - warning
        else:
            colors.append('#4CAF50')  # Зелёный - normal
    
    # Рисуем линию
    ax.plot(timestamps, values, linewidth=2, color='#2196F3', label='CPU Usage')
    
    # Закрашиваем зоны
    ax.fill_between(timestamps, 0, values, alpha=0.3, color='#2196F3')
    
    # Пороговые линии
    ax.axhline(y=80, color='red', linestyle='--', linewidth=1, alpha=0.7, label='Critical (80%)')
    ax.axhline(y=60, color='orange', linestyle='--', linewidth=1, alpha=0.7, label='Warning (60%)')
    
    # Настройка осей
    ax.set_xlabel('Время', fontsize=12, fontweight='bold')
    ax.set_ylabel('CPU Usage (%)', fontsize=12, fontweight='bold')
    ax.set_title('CPU Usage Over Time', fontsize=14, fontweight='bold')
    
    # Форматирование временной оси
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M'))
    plt.xticks(rotation=45, ha='right')
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle=':', linewidth=0.5)
    ax.set_ylim(0, 100)
    
    # Legend
    ax.legend(loc='upper left', framealpha=0.9)
    
    # Сохранение
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    logger.info(f"CPU график сохранён: {output_path}")
    return output_path


def create_memory_chart(timestamps: List[datetime], values: List[float], output_path: str) -> str:
    """
    Создаёт линейный график использования памяти
    
    Args:
        timestamps: Список временных меток
        values: Список значений Memory (%)
        output_path: Путь для сохранения графика
        
    Returns:
        Путь к созданному файлу
    """
    logger.debug(f"Создание Memory графика: {len(values)} точек")
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Рисуем линию
    ax.plot(timestamps, values, linewidth=2, color='#9C27B0', label='Memory Usage')
    
    # Закрашиваем зоны
    ax.fill_between(timestamps, 0, values, alpha=0.3, color='#9C27B0')
    
    # Пороговые линии
    ax.axhline(y=85, color='red', linestyle='--', linewidth=1, alpha=0.7, label='Critical (85%)')
    ax.axhline(y=70, color='orange', linestyle='--', linewidth=1, alpha=0.7, label='Warning (70%)')
    
    # Настройка осей
    ax.set_xlabel('Время', fontsize=12, fontweight='bold')
    ax.set_ylabel('Memory Usage (%)', fontsize=12, fontweight='bold')
    ax.set_title('Memory Usage Over Time', fontsize=14, fontweight='bold')
    
    # Форматирование временной оси
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M'))
    plt.xticks(rotation=45, ha='right')
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle=':', linewidth=0.5)
    ax.set_ylim(0, 100)
    
    # Legend
    ax.legend(loc='upper left', framealpha=0.9)
    
    # Сохранение
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    logger.info(f"Memory график сохранён: {output_path}")
    return output_path


def create_disk_chart(disk_data: List[Dict[str, Any]], output_path: str) -> str:
    """
    Создаёт bar chart использования дисков
    
    Args:
        disk_data: Список дисков с данными
        output_path: Путь для сохранения графика
        
    Returns:
        Путь к созданному файлу
    """
    logger.debug(f"Создание Disk графика: {len(disk_data)} дисков")
    
    if not disk_data:
        # Создаём пустой график
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, 'No disk data available', 
                horizontalalignment='center', verticalalignment='center',
                fontsize=14, color='gray')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return output_path
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Подготовка данных
    mountpoints = [disk.get('mountpoint', '/') for disk in disk_data]
    percentages = [disk.get('percent', 0) for disk in disk_data]
    
    # Цвета по порогам
    colors = []
    for percent in percentages:
        if percent >= 90:
            colors.append('#FF4444')  # Красный
        elif percent >= 75:
            colors.append('#FFA500')  # Оранжевый
        else:
            colors.append('#4CAF50')  # Зелёный
    
    # Bar chart
    bars = ax.barh(mountpoints, percentages, color=colors, alpha=0.8, edgecolor='black', linewidth=1)
    
    # Добавляем значения на столбцы
    for i, (bar, percent) in enumerate(zip(bars, percentages)):
        width = bar.get_width()
        ax.text(width + 2, bar.get_y() + bar.get_height()/2, 
                f'{percent:.1f}%',
                ha='left', va='center', fontweight='bold', fontsize=10)
    
    # Пороговые линии
    ax.axvline(x=90, color='red', linestyle='--', linewidth=1, alpha=0.7, label='Critical (90%)')
    ax.axvline(x=75, color='orange', linestyle='--', linewidth=1, alpha=0.7, label='Warning (75%)')
    
    # Настройка осей
    ax.set_xlabel('Usage (%)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Mount Point', fontsize=12, fontweight='bold')
    ax.set_title('Disk Usage by Mount Point', fontsize=14, fontweight='bold')
    ax.set_xlim(0, 105)
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle=':', linewidth=0.5, axis='x')
    
    # Legend
    ax.legend(loc='lower right', framealpha=0.9)
    
    # Сохранение
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    logger.info(f"Disk график сохранён: {output_path}")
    return output_path


def create_network_chart(
    timestamps: List[datetime], 
    rx_values: List[float], 
    tx_values: List[float], 
    output_path: str
) -> str:
    """
    Создаёт линейный график сетевого трафика
    
    Args:
        timestamps: Список временных меток
        rx_values: Список значений RX (MB/s)
        tx_values: Список значений TX (MB/s)
        output_path: Путь для сохранения графика
        
    Returns:
        Путь к созданному файлу
    """
    logger.debug(f"Создание Network графика: {len(timestamps)} точек")
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Рисуем линии
    ax.plot(timestamps, rx_values, linewidth=2, color='#2196F3', label='RX (Received)', marker='o', markersize=3)
    ax.plot(timestamps, tx_values, linewidth=2, color='#FF9800', label='TX (Transmitted)', marker='s', markersize=3)
    
    # Закрашиваем области
    ax.fill_between(timestamps, 0, rx_values, alpha=0.2, color='#2196F3')
    ax.fill_between(timestamps, 0, tx_values, alpha=0.2, color='#FF9800')
    
    # Настройка осей
    ax.set_xlabel('Время', fontsize=12, fontweight='bold')
    ax.set_ylabel('Traffic (MB/s)', fontsize=12, fontweight='bold')
    ax.set_title('Network Traffic Over Time', fontsize=14, fontweight='bold')
    
    # Форматирование временной оси
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M'))
    plt.xticks(rotation=45, ha='right')
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle=':', linewidth=0.5)
    
    # Legend
    ax.legend(loc='upper left', framealpha=0.9)
    
    # Сохранение
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    logger.info(f"Network график сохранён: {output_path}")
    return output_path




