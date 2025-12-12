#!/bin/bash
#
# Простой скрипт для поочередного запуска нагрузочных тестов
# MCP сервер будет обнаруживать аномалии и отправлять алерты в Telegram
#
# Использование: bash run_stress_tests.sh
#

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Параметры нагрузки
CPU_DURATION=120       # 2 минуты CPU spike
MEMORY_DURATION=120    # 2 минуты Memory leak
DISK_DURATION=120      # 2 минуты Disk I/O
PAUSE_BETWEEN=60       # 1 минута паузы между тестами

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           НАГРУЗОЧНЫЕ ТЕСТЫ ДЛЯ МОНИТОРИНГА                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}📌 MCP сервер должен быть запущен локально${NC}"
echo -e "${BLUE}📌 Telegram алерты должны быть настроены${NC}"
echo -e "${BLUE}📌 Наблюдайте за алертами в Telegram во время тестов${NC}"
echo ""

# Проверка наличия stress_test.py
if [ ! -f "scripts/stress_test.py" ]; then
    echo -e "${RED}❌ Файл stress_test.py не найден${NC}"
    exit 1
fi

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 не найден${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Все проверки пройдены${NC}"
echo ""
echo -e "${YELLOW}Будет выполнено:${NC}"
echo "  1. CPU Spike   - $CPU_DURATION сек"
echo "  2. Memory Leak - $MEMORY_DURATION сек"
echo "  3. Disk I/O    - $DISK_DURATION сек"
echo ""
echo -e "${YELLOW}Общее время: ~$((CPU_DURATION + MEMORY_DURATION + DISK_DURATION + PAUSE_BETWEEN * 2)) секунд (~$(((CPU_DURATION + MEMORY_DURATION + DISK_DURATION + PAUSE_BETWEEN * 2) / 60)) минут)${NC}"
echo ""

read -p "Начать тесты? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Отменено"
    exit 0
fi

echo ""

# ============================================================================
# ТЕСТ 1: CPU SPIKE
# ============================================================================

echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}ТЕСТ 1: CPU SPIKE${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}🔥 Запуск CPU stress test на $CPU_DURATION секунд...${NC}"
echo -e "${BLUE}📊 Следите за Telegram для алертов!${NC}"
echo ""

python3 scripts/stress_test.py --scenario cpu_spike --duration $CPU_DURATION

echo ""
echo -e "${GREEN}✅ CPU Spike test завершен${NC}"
echo -e "${YELLOW}⏳ Пауза $PAUSE_BETWEEN секунд перед следующим тестом...${NC}"
echo ""
sleep $PAUSE_BETWEEN

# ============================================================================
# ТЕСТ 2: MEMORY LEAK
# ============================================================================

echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}ТЕСТ 2: MEMORY LEAK${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}🔥 Запуск Memory stress test на $MEMORY_DURATION секунд...${NC}"
echo -e "${BLUE}📊 Следите за Telegram для алертов!${NC}"
echo ""

python3 scripts/stress_test.py --scenario memory_leak --duration $MEMORY_DURATION

echo ""
echo -e "${GREEN}✅ Memory Leak test завершен${NC}"
echo -e "${YELLOW}⏳ Пауза $PAUSE_BETWEEN секунд перед следующим тестом...${NC}"
echo ""
sleep $PAUSE_BETWEEN

# ============================================================================
# ТЕСТ 3: DISK I/O
# ============================================================================

echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}ТЕСТ 3: DISK I/O${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}🔥 Запуск Disk I/O stress test на $DISK_DURATION секунд...${NC}"
echo -e "${BLUE}📊 Следите за Telegram для алертов!${NC}"
echo ""

python3 scripts/stress_test.py --scenario disk_io --duration $DISK_DURATION

echo ""
echo -e "${GREEN}✅ Disk I/O test завершен${NC}"
echo ""

# ============================================================================
# ЗАВЕРШЕНИЕ
# ============================================================================

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              ВСЕ НАГРУЗОЧНЫЕ ТЕСТЫ ЗАВЕРШЕНЫ                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}📋 Проверьте:${NC}"
echo "  ✓ Алерты в Telegram"
echo "  ✓ Логи MCP сервера"
echo "  ✓ Графики в Grafana (если доступна)"
echo ""
echo -e "${BLUE}📊 Для отчета:${NC}"
echo "  1. Сделайте скриншоты Telegram алертов"
echo "  2. Сохраните логи MCP сервера"
echo "  3. Экспортируйте графики из Grafana"
echo ""
echo -e "${GREEN}✅ Готово!${NC}"

