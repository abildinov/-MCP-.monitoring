#!/bin/bash
#
# Скрипт для развертывания экспериментальных скриптов на удаленный сервер
# Использование: ./deploy_to_server.sh [user@]host
#

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Проверка аргументов
if [ $# -eq 0 ]; then
    echo -e "${RED}❌ Использование: $0 [user@]host${NC}"
    echo "   Пример: $0 root@147.45.157.2"
    exit 1
fi

SERVER=$1
# По умолчанию используем путь где уже есть инфраструктура мониторинга
PROJECT_DIR="/opt/monitoring-poc"

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          РАЗВЕРТЫВАНИЕ НА УДАЛЕННОМ СЕРВЕРЕ                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "🎯 Целевой сервер: $SERVER"
echo "📂 Директория проекта: $PROJECT_DIR"
echo ""

# Проверка подключения к серверу
echo "🔍 Проверка подключения к серверу..."
if ! ssh -o ConnectTimeout=5 $SERVER "echo 'OK'" > /dev/null 2>&1; then
    echo -e "${RED}❌ Не удалось подключиться к серверу${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Подключение к серверу установлено${NC}"
echo ""

# Проверка существования директории проекта
echo "🔍 Проверка директории проекта..."
if ssh $SERVER "[ -d $PROJECT_DIR ]"; then
    echo -e "${GREEN}✅ Директория $PROJECT_DIR существует${NC}"
else
    echo -e "${YELLOW}⚠️  Директория $PROJECT_DIR не найдена, создаем...${NC}"
    ssh $SERVER "sudo mkdir -p $PROJECT_DIR && sudo chown \$(whoami):\$(whoami) $PROJECT_DIR"
fi
echo ""

# Создание поддиректорий на сервере
echo "📁 Создание поддиректорий..."
ssh $SERVER "mkdir -p $PROJECT_DIR/scripts $PROJECT_DIR/mcp-server $PROJECT_DIR/experiments"
echo -e "${GREEN}✅ Директории созданы${NC}"
echo ""

# Копирование скриптов
echo "📦 Копирование файлов..."

echo "  - Копирование скриптов тестирования..."
scp scripts/stress_test.py $SERVER:$PROJECT_DIR/scripts/
scp scripts/collect_experiment_data.py $SERVER:$PROJECT_DIR/scripts/
scp scripts/analyze_results.py $SERVER:$PROJECT_DIR/scripts/
scp scripts/run_full_experiment.sh $SERVER:$PROJECT_DIR/scripts/

echo "  - Копирование MCP серверных модулей..."
scp -r mcp-server/clients $SERVER:$PROJECT_DIR/mcp-server/
scp -r mcp-server/analytics $SERVER:$PROJECT_DIR/mcp-server/
scp mcp-server/config.py $SERVER:$PROJECT_DIR/mcp-server/
scp mcp-server/.env $SERVER:$PROJECT_DIR/mcp-server/ 2>/dev/null || echo "  (файл .env не найден, пропущен)"
scp mcp-server/requirements.txt $SERVER:$PROJECT_DIR/mcp-server/

echo -e "${GREEN}✅ Файлы скопированы${NC}"
echo ""

# Установка прав на выполнение
echo "🔐 Установка прав на выполнение..."
ssh $SERVER "chmod +x $PROJECT_DIR/scripts/*.sh"
ssh $SERVER "chmod +x $PROJECT_DIR/scripts/*.py"
echo -e "${GREEN}✅ Права установлены${NC}"
echo ""

# Проверка Python и установка зависимостей
echo "🐍 Проверка Python и зависимостей..."
ssh $SERVER << ENDSSH
set -e

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 не установлен"
    exit 1
fi
echo "✅ Python 3 доступен"

# Проверка pip
if ! command -v pip3 &> /dev/null; then
    echo "⚙️ Установка pip..."
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3
fi
echo "✅ pip доступен"

# Установка зависимостей
cd $PROJECT_DIR
echo "⚙️ Установка Python зависимостей..."
pip3 install --quiet --upgrade pip
pip3 install --quiet numpy matplotlib httpx aiohttp pydantic pydantic-settings python-dotenv loguru

echo "✅ Зависимости установлены"

# Проверка stress-ng (опционально)
if ! command -v stress-ng &> /dev/null; then
    echo "⚠️ stress-ng не установлен (будет использован Python fallback)"
    echo "   Для установки: sudo apt-get install stress-ng"
else
    echo "✅ stress-ng доступен"
fi

ENDSSH

echo -e "${GREEN}✅ Проверка зависимостей завершена${NC}"
echo ""

# Итоговая информация
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                  РАЗВЕРТЫВАНИЕ ЗАВЕРШЕНО                     ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "📋 Следующие шаги:"
echo ""
echo "1. Подключитесь к серверу:"
echo "   ssh $SERVER"
echo ""
echo "2. Перейдите в директорию проекта:"
echo "   cd $PROJECT_DIR"
echo ""
echo "3. Запустите эксперименты:"
echo "   bash scripts/run_full_experiment.sh"
echo ""
echo "4. Скачайте результаты обратно:"
echo "   scp -r $SERVER:$PROJECT_DIR/experiments/ ."
echo ""
echo -e "${GREEN}✅ Готово!${NC}"

