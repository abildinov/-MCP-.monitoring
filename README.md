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

## Как запустить

### Шаг 1: Docker контейнеры

```bash
docker-compose up -d
docker ps  # проверяем что все запустилось
```

Должны быть доступны:
- Grafana: http://147.45.157.2:3000 ()
- Prometheus: http://147.45.157.2:9090
- Loki: http://147.45.157.2:3100

Если порты другие - посмотри в docker-compose.yml

### Шаг 2: Настройка .env

```bash
cp env.example .env
# отредактируй файл и добавь свои ключи
```

Минимум что нужно:
- `DEEPSEEK_API_KEY` - получи ключ в TimeWeb Cloud
- `TELEGRAM_BOT_TOKEN` - получи токен от @BotFather

### Шаг 3: Запуск MCP и бота

Вариант 1 - все вместе:
```bash
cd mcp-server
pip install -r requirements.txt  # если еще не ставил
cd ..
python scripts/start_all.py
```

Вариант 2 - по отдельности (удобнее для отладки):

В одном терминале MCP сервер:
```bash
python mcp-server/server.py --transport http
```

В другом терминале бот:
```bash
python scripts/telegram_monitoring_bot.py
```

P.S. Возможно нужно будет установить зависимости если первый раз запускаешь

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

Кстати, все функции async, не забывай await.

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

## Проблемы и решения

**MCP сервер не запускается:**
- Проверь .env файл - токены на месте?
- Prometheus и Loki работают? (`docker ps`)
- Смотри логи: `python mcp-server/server.py`

**Telegram бот молчит:**
- Проверь TELEGRAM_BOT_TOKEN в .env
- MCP сервер запущен? Проверь `curl http://localhost:8000/health`
- Логи бота покажут что не так

**Метрики не приходят:**
- Все Docker контейнеры работают? (`docker ps`)
- Логи Prometheus: `docker logs prometheus`
- IP адрес в env правильный? Должен быть 147.45.157.2 (или другой твой)

**Grafana пусто:**
- В Grafana UI проверь datasources
- Prometheus: http://prometheus:9090
- Loki: http://loki:3100

P.S. Если порты не совпадают - проверь docker-compose.yml

## Как добавить новый MCP tool

Если нужно больше функционала:

1. Открой `mcp-server/server.py`
2. В `list_tools()` добавь Tool
3. В `call_tool()` добавь elif для нового tool
4. Напиши функцию `async def tool_my_new_tool()`

Простой пример:
```python
# 1. В list_tools() добавить
Tool(name="get_something", description="...", inputSchema={})

# 2. В call_tool() добавить
elif name == "get_something":
    return await tool_get_something()

# 3. Реализовать
async def tool_get_something() -> list[TextContent]:
    # собрать данные из prometheus_client
    data = await prometheus_client.get_current_cpu()
    
    # можно отправить на анализ через LLM
    analysis = await llm_client.analyze_metrics(data, context="...")
    
    return [TextContent(type="text", text=result)]
```

Смотри существующие tools (`get_cpu_usage`, `get_memory_status`) для примеров.



## Что еще в планах

- [ ] **Экспорт отчётов через бота** (PDF/Excel)
  - Генерация PDF отчётов с метриками и графиками
  - Экспорт данных в Excel таблицы
  - Интеграция с Grafana Renderer для экспорта дашбордов
- [ ] WebUI для просмотра метрик (без Telegram)
- [ ] Экспорт метрик наружу (в другой Prometheus)
- [ ] Поддержка нескольких серверов
- [ ] Slack бот вместо/в дополнение к Telegram
- [ ] Email уведомления при критических алертах
- [ ] Исторические отчёты за период (день/неделя/месяц)

## Заметки

В Grafana уже есть готовые дашборды в `dashboards/exported/`, их можно импортировать.

Данные на сервере `147.45.157.2`, если что поменяй на свой IP в docker-compose.yml и .env.

## Лицензия

MIT
