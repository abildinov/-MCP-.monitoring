"""
PDF report generator with charts and LLM analysis
"""

import os
import tempfile
from datetime import datetime
from typing import Dict, Any
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, black
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from loguru import logger

import sys
mcp_server_path = Path(__file__).parent.parent
if str(mcp_server_path) not in sys.path:
    sys.path.insert(0, str(mcp_server_path))

from .data_collector import collect_metrics_for_period
from .chart_generator import create_cpu_chart, create_memory_chart, create_disk_chart, create_network_chart
from llm.universal_client import UniversalLLMClient


def _register_fonts():
    """Регистрация шрифтов с поддержкой кириллицы"""
    try:
        # Пытаемся использовать DejaVu Sans (обычно есть в системе)
        # Для Windows ищем в стандартных путях
        import platform
        
        if platform.system() == 'Windows':
            # Стандартные пути Windows
            font_paths = [
                'C:/Windows/Fonts/DejaVuSans.ttf',
                'C:/Windows/Fonts/arial.ttf',
                'C:/Windows/Fonts/calibri.ttf',
            ]
            bold_paths = [
                'C:/Windows/Fonts/DejaVuSans-Bold.ttf',
                'C:/Windows/Fonts/arialbd.ttf',
                'C:/Windows/Fonts/calibrib.ttf',
            ]
        else:
            # Linux/Mac пути
            font_paths = [
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
                '/System/Library/Fonts/Helvetica.ttc',
            ]
            bold_paths = [
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
                '/System/Library/Fonts/Helvetica.ttc',
            ]
        
        # Ищем первый доступный шрифт
        font_registered = False
        for font_path, bold_path in zip(font_paths, bold_paths):
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont('CustomFont', font_path))
                    if os.path.exists(bold_path):
                        pdfmetrics.registerFont(TTFont('CustomFont-Bold', bold_path))
                    else:
                        pdfmetrics.registerFont(TTFont('CustomFont-Bold', font_path))
                    font_registered = True
                    logger.info(f"Зарегистрирован шрифт: {font_path}")
                    break
                except Exception as e:
                    logger.warning(f"Не удалось зарегистрировать {font_path}: {e}")
                    continue
        
        if not font_registered:
            logger.warning("Кириллические шрифты не найдены, используем стандартные (без кириллицы)")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка регистрации шрифтов: {e}")
        return False


async def generate_pdf_report(
    period: str,
    output_path: str = None,
    prometheus_url: str = "http://147.45.157.2:9090",
    loki_url: str = "http://147.45.157.2:3100"
) -> str:
    """
    Генерирует PDF отчёт с графиками и LLM анализом
    
    Args:
        period: Период ("24h", "7d", "30d")
        output_path: Путь для сохранения файла
        prometheus_url: URL Prometheus
        loki_url: URL Loki
        
    Returns:
        Путь к созданному файлу
    """
    logger.info(f"Генерация PDF отчёта за период: {period}")
    
    # Регистрируем шрифты с поддержкой кириллицы
    fonts_registered = _register_fonts()
    
    # Собираем данные
    data = await collect_metrics_for_period(period, prometheus_url, loki_url)
    
    # Создаём путь к файлу если не указан
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, f"report_{period}_{timestamp}.pdf")
    
    # Генерируем AI анализ
    logger.info("Запрос AI анализа...")
    llm_client = UniversalLLMClient()
    ai_analysis = await llm_client.generate_report_analysis(data, period)
    logger.info("AI анализ получен")
    
    # Создаём графики
    temp_dir = tempfile.gettempdir()
    chart_files = await _generate_charts(data, temp_dir, period)
    
    # Создаём PDF
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    # Элементы документа
    story = []
    styles = getSampleStyleSheet()
    
    # Добавляем кастомные стили
    _add_custom_styles(styles)
    
    # 1. Обложка
    _add_cover_page(story, styles, data, period)
    story.append(PageBreak())
    
    # 2. AI Анализ
    _add_ai_analysis_section(story, styles, ai_analysis)
    story.append(PageBreak())
    
    # 3. Графики
    _add_charts_section(story, styles, chart_files)
    story.append(PageBreak())
    
    # 4. Детальная статистика
    _add_statistics_section(story, styles, data)
    story.append(PageBreak())
    
    # 5. Алерты
    _add_alerts_section(story, styles, data)
    
    # 6. Ошибки
    if data.get('errors'):
        story.append(PageBreak())
        _add_errors_section(story, styles, data)
    
    # Генерируем PDF
    doc.build(story)
    
    # Удаляем временные файлы графиков
    for chart_file in chart_files.values():
        try:
            if os.path.exists(chart_file):
                os.remove(chart_file)
        except Exception as e:
            logger.warning(f"Не удалось удалить временный файл {chart_file}: {e}")
    
    logger.info(f"PDF отчёт сохранён: {output_path}")
    return output_path


async def _generate_charts(data: Dict[str, Any], temp_dir: str, period: str) -> Dict[str, str]:
    """Генерирует все графики для отчёта"""
    logger.info("Генерация графиков...")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    charts = {}
    
    # CPU chart
    cpu = data.get('cpu', {})
    if cpu.get('timestamps') and cpu.get('values'):
        cpu_path = os.path.join(temp_dir, f"chart_cpu_{timestamp}.png")
        create_cpu_chart(cpu['timestamps'], cpu['values'], cpu_path)
        charts['cpu'] = cpu_path
    
    # Memory chart
    memory = data.get('memory', {})
    if memory.get('timestamps') and memory.get('values'):
        memory_path = os.path.join(temp_dir, f"chart_memory_{timestamp}.png")
        create_memory_chart(memory['timestamps'], memory['values'], memory_path)
        charts['memory'] = memory_path
    
    # Disk chart
    disk = data.get('disk', {})
    if disk.get('disks'):
        disk_path = os.path.join(temp_dir, f"chart_disk_{timestamp}.png")
        create_disk_chart(disk['disks'], disk_path)
        charts['disk'] = disk_path
    
    # Network chart - создаём если есть данные
    network = data.get('network', {})
    # Для network нужны временные ряды, которых у нас пока нет в сборщике
    # Оставим заглушку
    
    logger.info(f"Сгенерировано графиков: {len(charts)}")
    return charts


def _add_custom_styles(styles):
    """Добавляет кастомные стили"""
    # Обновляем дефолтный Normal style
    styles['Normal'].fontName = 'CustomFont'
    styles['Normal'].fontSize = 10
    
    # Заголовок секции
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=HexColor('#2196F3'),
        spaceAfter=12,
        spaceBefore=12,
        fontName='CustomFont-Bold'
    ))
    
    # Подзаголовок
    styles.add(ParagraphStyle(
        name='SubHeader',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=HexColor('#666666'),
        spaceAfter=8,
        spaceBefore=8,
        fontName='CustomFont-Bold'
    ))
    
    # AI текст
    styles.add(ParagraphStyle(
        name='AIText',
        parent=styles['BodyText'],
        fontSize=10,
        leading=14,
        spaceAfter=6,
        fontName='CustomFont'
    ))


def _add_cover_page(story, styles, data: Dict[str, Any], period: str):
    """Добавляет обложку"""
    period_names = {"24h": "24 часа", "7d": "7 дней", "30d": "30 дней"}
    period_name = period_names.get(period, period)
    
    # Заголовок
    title_style = ParagraphStyle(
        name='Title',
        parent=styles['Title'],
        fontSize=24,
        textColor=HexColor('#2196F3'),
        alignment=TA_CENTER,
        spaceAfter=30,
        fontName='CustomFont-Bold'
    )
    
    story.append(Spacer(1, 5*cm))
    story.append(Paragraph("ОТЧЁТ О СИСТЕМЕ МОНИТОРИНГА", title_style))
    story.append(Spacer(1, 2*cm))
    
    # Информация о периоде
    info_style = ParagraphStyle(
        name='CoverInfo',
        parent=styles['Normal'],
        fontSize=14,
        alignment=TA_CENTER,
        spaceAfter=10,
        fontName='CustomFont'
    )
    
    story.append(Paragraph(f"<b>Период:</b> {period_name}", info_style))
    story.append(Paragraph(f"<b>Начало:</b> {data['start_time'][:16]}", info_style))
    story.append(Paragraph(f"<b>Конец:</b> {data['end_time'][:16]}", info_style))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(f"<b>Дата генерации:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}", info_style))
    
    # Краткая сводка
    story.append(Spacer(1, 3*cm))
    summary_style = ParagraphStyle(
        name='Summary',
        parent=styles['Normal'],
        fontSize=11,
        alignment=TA_LEFT,
        leftIndent=2*cm,
        rightIndent=2*cm,
        fontName='CustomFont'
    )
    
    cpu = data.get('cpu', {})
    memory = data.get('memory', {})
    alerts = data.get('alerts', [])
    
    firing_alerts = [a for a in alerts if a.get('state') in ['firing_now', 'firing']]
    
    summary_text = f"""
    <b>Краткая сводка:</b><br/>
    • CPU: среднее {cpu.get('avg', 0):.1f}%, максимум {cpu.get('max', 0):.1f}%<br/>
    • Memory: среднее {memory.get('avg', 0):.1f}%, максимум {memory.get('max', 0):.1f}%<br/>
    • Активных алертов: {len(firing_alerts)}<br/>
    • Ошибок в логах: {len(data.get('errors', []))}
    """
    
    story.append(Paragraph(summary_text, summary_style))


def _escape_xml(text: str) -> str:
    """Экранирует специальные XML символы для reportlab"""
    # Экранируем основные символы
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    text = text.replace("'", '&apos;')
    return text


def _convert_markdown_to_reportlab(text: str) -> str:
    """Конвертирует markdown синтаксис в reportlab теги"""
    import re
    
    # Сначала экранируем XML символы (но не затрагиваем markdown **)
    # Временно заменяем ** на placeholder
    text = text.replace('**', '<<<BOLD_MARKER>>>')
    
    # Экранируем XML
    text = _escape_xml(text)
    
    # Теперь обрабатываем markdown bold
    # Заменяем парные <<<BOLD_MARKER>>> на <b> и </b>
    parts = text.split('<<<BOLD_MARKER>>>')
    
    # Если нечетное количество маркеров - просто удаляем их
    if len(parts) % 2 == 0:
        # Четное количество - можем парно заменить
        result = []
        for i, part in enumerate(parts):
            if i % 2 == 0:
                result.append(part)
            else:
                # Это текст между ** **
                result.append(f'<b>{part}</b>')
        text = ''.join(result)
    else:
        # Нечетное - просто убираем маркеры
        text = ''.join(parts)
    
    # Заменяем переводы строк на <br/>
    text = text.replace('\n', '<br/>')
    
    return text


def _add_ai_analysis_section(story, styles, ai_analysis: str):
    """Добавляет секцию с AI анализом"""
    story.append(Paragraph("AI АНАЛИЗ СИСТЕМЫ", styles['SectionHeader']))
    story.append(Spacer(1, 0.5*cm))
    
    # Разбиваем анализ на параграфы
    paragraphs = ai_analysis.split('\n\n')
    
    for para in paragraphs:
        if para.strip():
            # Проверяем заголовки (начинаются с #)
            if para.strip().startswith('#'):
                # Убираем # и делаем заголовком
                header_text = para.strip().lstrip('#').strip()
                # Экранируем специальные символы XML
                header_text = _escape_xml(header_text)
                story.append(Paragraph(header_text, styles['SubHeader']))
            else:
                # Обычный текст
                # Правильно заменяем markdown bold на reportlab bold
                para = _convert_markdown_to_reportlab(para)
                story.append(Paragraph(para, styles['AIText']))
            
            story.append(Spacer(1, 0.3*cm))


def _add_charts_section(story, styles, chart_files: Dict[str, str]):
    """Добавляет секцию с графиками"""
    story.append(Paragraph("ГРАФИКИ МЕТРИК", styles['SectionHeader']))
    story.append(Spacer(1, 0.5*cm))
    
    # CPU
    if 'cpu' in chart_files and os.path.exists(chart_files['cpu']):
        story.append(Paragraph("CPU Usage", styles['SubHeader']))
        img = Image(chart_files['cpu'], width=16*cm, height=9.6*cm)
        story.append(img)
        story.append(Spacer(1, 1*cm))
    
    # Memory
    if 'memory' in chart_files and os.path.exists(chart_files['memory']):
        story.append(Paragraph("Memory Usage", styles['SubHeader']))
        img = Image(chart_files['memory'], width=16*cm, height=9.6*cm)
        story.append(img)
        story.append(Spacer(1, 1*cm))
    
    # Disk
    if 'disk' in chart_files and os.path.exists(chart_files['disk']):
        story.append(Paragraph("Disk Usage", styles['SubHeader']))
        img = Image(chart_files['disk'], width=16*cm, height=9.6*cm)
        story.append(img)


def _add_statistics_section(story, styles, data: Dict[str, Any]):
    """Добавляет секцию детальной статистики"""
    story.append(Paragraph("ДЕТАЛЬНАЯ СТАТИСТИКА", styles['SectionHeader']))
    story.append(Spacer(1, 0.5*cm))
    
    # CPU статистика
    cpu = data.get('cpu', {})
    story.append(Paragraph("CPU Metrics", styles['SubHeader']))
    
    cpu_data = [
        ['Метрика', 'Значение', 'Статус'],
        ['Текущее', f"{cpu.get('current', 0):.2f}%", _get_status_text(cpu.get('current', 0), 80)],
        ['Среднее', f"{cpu.get('avg', 0):.2f}%", _get_status_text(cpu.get('avg', 0), 80)],
        ['Медиана', f"{cpu.get('median', 0):.2f}%", _get_status_text(cpu.get('median', 0), 80)],
        ['Минимум', f"{cpu.get('min', 0):.2f}%", ''],
        ['Максимум', f"{cpu.get('max', 0):.2f}%", ''],
        ['95 процентиль', f"{cpu.get('p95', 0):.2f}%", _get_status_text(cpu.get('p95', 0), 80)],
        ['Тренд', cpu.get('trend', 'N/A'), '']
    ]
    
    cpu_table = Table(cpu_data, colWidths=[5*cm, 4*cm, 4*cm])
    cpu_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2196F3')),
        ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#FFFFFF')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'CustomFont-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'CustomFont'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 0.5, black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#F5F5F5'), HexColor('#FFFFFF')])
    ]))
    
    story.append(cpu_table)
    story.append(Spacer(1, 1*cm))
    
    # Memory статистика
    memory = data.get('memory', {})
    story.append(Paragraph("Memory Metrics", styles['SubHeader']))
    
    memory_data = [
        ['Метрика', 'Значение', 'Статус'],
        ['Общая память', f"{memory.get('total_gb', 0):.2f} GB", ''],
        ['Текущее', f"{memory.get('current', 0):.2f}%", _get_status_text(memory.get('current', 0), 85)],
        ['Среднее', f"{memory.get('avg', 0):.2f}%", _get_status_text(memory.get('avg', 0), 85)],
        ['Медиана', f"{memory.get('median', 0):.2f}%", _get_status_text(memory.get('median', 0), 85)],
        ['Минимум', f"{memory.get('min', 0):.2f}%", ''],
        ['Максимум', f"{memory.get('max', 0):.2f}%", ''],
        ['95 процентиль', f"{memory.get('p95', 0):.2f}%", _get_status_text(memory.get('p95', 0), 85)],
        ['Тренд', memory.get('trend', 'N/A'), '']
    ]
    
    memory_table = Table(memory_data, colWidths=[5*cm, 4*cm, 4*cm])
    memory_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#9C27B0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#FFFFFF')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'CustomFont-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'CustomFont'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 0.5, black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#F5F5F5'), HexColor('#FFFFFF')])
    ]))
    
    story.append(memory_table)
    story.append(Spacer(1, 1*cm))
    
    # Top Processes
    processes = data.get('processes', [])
    if processes:
        story.append(Paragraph("Top Processes by CPU", styles['SubHeader']))
        
        proc_data = [['Rank', 'Process Name', 'CPU Usage']]
        for proc in processes[:10]:
            proc_data.append([
                str(proc.get('rank', '')),
                proc.get('name', 'unknown'),
                f"{proc.get('cpu_usage', 0):.2f}%"
            ])
        
        proc_table = Table(proc_data, colWidths=[2*cm, 8*cm, 3*cm])
        proc_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#4CAF50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#FFFFFF')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'CustomFont-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'CustomFont'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#F5F5F5'), HexColor('#FFFFFF')])
        ]))
        
        story.append(proc_table)


def _add_alerts_section(story, styles, data: Dict[str, Any]):
    """Добавляет секцию с алертами"""
    story.append(Paragraph("ИСТОРИЯ АЛЕРТОВ", styles['SectionHeader']))
    story.append(Spacer(1, 0.5*cm))
    
    alerts = data.get('alerts', [])
    
    if not alerts:
        story.append(Paragraph("Алертов за период не зафиксировано", styles['Normal']))
        return
    
    # Сортируем: сначала активные
    sorted_alerts = sorted(
        alerts,
        key=lambda x: (x.get('state') != 'firing_now', -x.get('firing_count', 0))
    )
    
    alert_data = [['Alert Name', 'Severity', 'Status', 'Firing Count']]
    
    for alert in sorted_alerts[:15]:  # Топ 15
        status = alert.get('state', 'unknown')
        status_text = {
            'firing_now': 'ACTIVE NOW',
            'fired_in_period': 'Fired',
            'unknown': 'Unknown'
        }.get(status, status)
        
        alert_data.append([
            alert.get('name', 'Unknown'),
            alert.get('severity', 'unknown'),
            status_text,
            str(alert.get('firing_count', 0))
        ])
    
    alert_table = Table(alert_data, colWidths=[6*cm, 3*cm, 3*cm, 2*cm])
    alert_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#FF5722')),
        ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#FFFFFF')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'CustomFont-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'CustomFont'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 0.5, black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#FFEBEE'), HexColor('#FFFFFF')])
    ]))
    
    story.append(alert_table)


def _add_errors_section(story, styles, data: Dict[str, Any]):
    """Добавляет секцию с ошибками"""
    story.append(Paragraph("ОШИБКИ ИЗ ЛОГОВ", styles['SectionHeader']))
    story.append(Spacer(1, 0.5*cm))
    
    errors = data.get('errors', [])
    
    if not errors:
        story.append(Paragraph("Критичных ошибок не обнаружено", styles['Normal']))
        return
    
    error_data = [['Timestamp', 'Container', 'Message']]
    
    for error in errors[:20]:  # Первые 20
        message = error.get('message', '')
        if len(message) > 80:
            message = message[:77] + '...'
        
        error_data.append([
            error.get('timestamp', '')[:16],
            error.get('container', 'unknown'),
            message
        ])
    
    error_table = Table(error_data, colWidths=[3*cm, 3*cm, 8*cm])
    error_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#F44336')),
        ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#FFFFFF')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'CustomFont-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'CustomFont'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 0.5, black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#FFEBEE'), HexColor('#FFFFFF')]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP')
    ]))
    
    story.append(error_table)


def _get_status_text(value: float, threshold: float) -> str:
    """Возвращает текст статуса"""
    if value >= threshold:
        return 'HIGH'
    elif value >= threshold * 0.8:
        return 'WARNING'
    else:
        return 'NORMAL'

