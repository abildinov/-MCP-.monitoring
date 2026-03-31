# 🚀 Система мониторинга с AI анализом

Система мониторинга на Prometheus/Loki/Grafana + DeepSeek V3.1 через Telegram бот.

## Что это за проект

Система мониторинга сервера с AI-анализом, состоит из двух частей:

1. **Инфраструктурная часть** - все на Docker (Prometheus, Loki, Grafana, etc)
2. **AI часть** - Python скрипты которые цепляются к метрикам и анализируют их через DeepSeek

Все это работает через MCP сервер (Model Context Protocol), который можно использовать из Telegram бота или напрямую.

Порт MCP сервера: 8000 

## Архитектура проекта

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          DOCKER INFRASTRUCTURE                           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   ┌──────────────┐      ┌──────────────┐      ┌──────────────┐          │
│   │   Prometheus │      │     Loki     │      │   Grafana    │          │
│   │    :9090     │      │    :3100     │      │    :3000     │          │
│   └──────┬───────┘      └──────┬───────┘      └──────┬───────┘          │
│          │                     │                     │                   │
│          │ scrape              │ query               │ visualize         │
│          │                     │                     │                   │
│   ┌──────▼───────┐      ┌──────▼───────┐      ┌──────▼───────┐          │
│   │ Node Exporter│◄─────┤   Promtail   │      │  Dashboards  │          │
│   │    :9100     │      │  (collector) │      │  + Alerts    │          │
│   └──────┬───────┘      └──────┬───────┘      └──────────────┘          │
│          │                     │                                         │
│          │                     │ docker logs                             │
│          │                     │                                         │
│   ┌──────▼───────┐             │                                         │
│   │  cAdvisor    │             │                                         │
│   │    :8080     │◄────────────┘                                         │
│   │  (containers)│                                                        │
│   └──────────────┘                                                        │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
                                      ▲
                                      │ API calls
                                      │
┌──────────────────────────────────────────────────────────────────────────┐
│                          MCP SERVER (Python)                              │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   ┌─────────────────────────────────────────────────────────────┐        │
│   │  MCP Tools (8 инструментов)                                   │        │
│   │  ├─ get_cpu_usage        ├─ get_memory_status              │        │
│   │  ├─ get_disk_usage       ├─ get_network_status             │        │
│   │  ├─ get_top_processes    ├─ search_error_logs              │        │
│   │  ├─ get_active_alerts    └─ analyze_full_system            │        │
│   └─────────────────────────────────────────────────────────────┘        │
│                                                                           │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                  │
│   │ Prometheus  │    │   Loki      │    │  DeepSeek   │                  │
│   │   Client    │───▶│   Client    │    │  V3.1 LLM   │                  │
│   └─────────────┘    └─────────────┘    └──────┬──────┘                  │
│        │              │                        │                         │
│        │ get metrics  │ get logs               │ AI analysis              │
│        ▼              ▼                        │                         │
│   ┌──────────┐  ┌──────────┐                │                         │
│   │ CPU/Mem/  │  │ Errors/  │                ▼                         │
│   │ Disk/Net  │  │ Logs     │         ┌──────────────┐                 │
│   └──────────┘  └──────────┘         │ TimeWeb Cloud │                 │
│                                      │    API       │                 │
│                                      └──────────────┘                 │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
                                      ▲
                                      │ HTTP API
                                      │ localhost:8000
                                      │
┌──────────────────────────────────────────────────────────────────────────┐
│                          CLIENTS                                         │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   ┌──────────────────┐           ┌──────────────────┐                      │
│   │  Telegram Bot    │           │  MCP Client     │                      │
│   │                  │           │  (Python)       │                      │
│   │  Commands:       │           │                 │                      │
│   │  /start           │           │  call_tool()    │                      │
│   │  /status          │           │  get_*()         │                      │
│   │  /analyze          │           │                 │                      │
│   │  /chat             │           │                 │                      │
│   └──────────────────┘           └──────────────────┘                      │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

### Поток данных

**1. Сбор метрик:**
```
Docker Container Logs → Promtail → Loki
System metrics → Node Exporter → Prometheus
Container metrics → cAdvisor → Prometheus
```

**2. Анализ:**
```
User → Telegram Bot → MCP Server
MCP Server → Prometheus Client (query metrics)
MCP Server → Loki Client (query logs)
MCP Server → DeepSeek LLM (analyze data)
DeepSeek → LLM response → User
```

**3. Визуализация:**
```
Prometheus → Grafana (dashboards)
Loki → Grafana (logs)
Prometheus alerts → Grafana (alerts panel)
```

## Структура проекта

```
monitoring-poc/
├── docker-compose.yml          # Docker конфигурация
├── prometheus/
│   ├── prometheus.yml          # Конфиг Prometheus
│   └── alerts.yml              # Правила алертинга
├── loki/
│   └── local-config.yaml       # Конфиг Loki
├── promtail/
│   └── config.yml              # Сбор логов Docker
├── mcp-server/
│   ├── server.py               # Основной MCP сервер
│   ├── clients/               # Клиенты Prometheus, Loki
│   ├── llm/                    # DeepSeek клиент
│   └── config.py               # Настройки
├── scripts/
│   ├── telegram_monitoring_bot.py  # Telegram бот
│   └── mcp_client.py           # MCP клиент
└── dashboards/                 # Экспортированные Grafana дашборды
```

## Доступные команды

MCP сервер дает 8 инструментов, из них самые полезные:

**Базовые:**
- `get_cpu_usage` - CPU с анализом DeepSeek
- `get_memory_status` - память
- `get_disk_usage` - диски

**Продвинутые:**
- `get_network_status` - сеть (трафик + ошибки)
- `get_top_processes` - топ процессов и контейнеров

**Аналитика:**
- `search_error_logs` - ищет ошибки в Loki
- `analyze_full_system` - собирает ВСЕ метрики и анализирует

Есть еще `get_cpu_usage_raw` - быстро без LLM анализа, но редко юзал.

## Использование

### Через Telegram бота

Команды:
- `/start` - приветствие и меню с кнопками
- `/status` - все метрики в сыром виде (много данных)
- `/analyze` - AI анализ всего (медленнее, но с выводами)
- `/chat` - можно общаться с ботом, он знает про систему
- `/help` - справка

**Отчёты (Excel/PDF):**
- `/report_daily` - выбор формата отчёта за сутки
- `/report_weekly` - выбор формата отчёта за неделю
- `/report_monthly` - выбор формата отчёта за месяц

**Форматы отчётов:**
- **Excel**: детальные таблицы, временные ряды, статистика (8 листов: сводка, CPU, Memory, Disk, Network, Alerts, Errors, Top Processes)
- **PDF с AI**: графики + полный профессиональный анализ от DeepSeek V3.1 (обложка, AI анализ, графики, детальная статистика, алерты, ошибки)

Самое полезное - это `/analyze`, он реально анализирует и дает рекомендации.

Чтобы выйти из чата - `/end_chat`

### Через Python код

Если хочешь юзать MCP из своего кода:

```python
from scripts.mcp_client import MCPClient
import asyncio

async def main():
    client = MCPClient("http://localhost:8000")
    
    # Про CPU
    result = await client.call_tool("get_cpu_usage")
    print(result)
    
    # Полный анализ
    full = await client.call_tool("analyze_full_system")
    print(full)
    
    await client.close()

asyncio.run(main())
```


## Алерты

Настроены 5 алертов в Prometheus:

| Алерт | Когда срабатывает | Сложность |
|-------|-------------------|-----------|
| HighCPUUsage | CPU >80% | warning |
| HighMemoryUsage | Память >85% | warning |
| HighDiskUsage | Диск >90% | critical (самый важный) |
| NetworkErrors | Есть сетевые ошибки | warning |
| HighNetworkTraffic | >100MB/s | info (может быть нормой) |

Все в `prometheus/alerts.yml`, можешь отредактировать пороги.

Кстати, если алерт сработал - AI видит это и обязательно упомянет в анализе.

## Как работает AI анализ

DeepSeek V3.1 видит следующее:

**Метрики которые собираются:**
- CPU с трендом (↑ вверх, ↓ вниз, → стабильно)
- Memory + сколько доступно
- Диски с IO статистикой
- Сеть: трафик, соединения, ошибки
- Топ процессов по CPU/памяти
- Контейнеры через cAdvisor

**Плюс контекст:**
- Активные алерты (если CPU упал - это проблема!)
- Ошибки из логов Loki
- 5 минутные тренды (min/avg/max)

**Формат ответа AI:**
1. СТАТУС - что сейчас с системой
2. ПРОБЛЕМЫ - если есть проблемы
3. РЕКОМЕНДАЦИИ - что стоит сделать
4. ПРОГНОЗ - что будет если нагрузка вырастет в 2-3 раза

Кстати, AI настроен на краткость - не больше 300 символов обычно. Чтобы не засорять чат.

## Технологии

**Python часть:**
- Python 3.9+, asyncio везде
- FastAPI для HTTP API
- httpx для всех HTTP запросов
- loguru для красивого логирования

**Мониторинг (Docker):**
- Prometheus - метрики
- Node Exporter - системные метрики хоста
- Loki - логи
- Promtail - сбор логов из Docker
- Grafana - визуализация
- cAdvisor - метрики контейнеров

**AI:**
- DeepSeek V3.1
- MCP протокол
- TimeWeb Cloud API (там висит модель)

**Telegram:**
- Используется httpx напрямую (упрощенная версия, но работает)

## Конфигурация

**Пороги мониторинга** (в .env):
```
CPU_THRESHOLD=80
MEMORY_THRESHOLD=85
DISK_THRESHOLD=90
```

Эти же пороги используются и в AI анализе - если CPU >80%, AI скажет что это проблема.

**DeepSeek настройки**:
```
DEEPSEEK_MAX_TOKENS=320        # короткий ответ
DEEPSEEK_TEMPERATURE=0.2       # более точные ответы
```

Температура 0.2 - специально низкая чтобы ответы были стабильными и не "креативил". Для мониторинга это лучше.




## Лицензия

MIT
