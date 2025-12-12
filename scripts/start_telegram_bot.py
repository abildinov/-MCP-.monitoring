#!/usr/bin/env python3
"""
Простой скрипт для запуска Telegram бота мониторинга
"""

import asyncio
import sys
from pathlib import Path

# Добавляем путь к mcp-server для импорта модулей
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp-server"))

from telegram_monitoring_bot import TelegramMonitoringBot
from config import settings


async def main():
    """Запуск бота"""
    print("Запуск Telegram бота мониторинга...")
    
    # Проверяем настройки
    if not settings.telegram_enabled:
        print("Telegram не включен в настройках!")
        print("Установите TELEGRAM_ENABLED=true в .env файле")
        return 1
    
    if not settings.telegram_bot_token:
        print("Токен бота не настроен!")
        print("Запустите: python setup_telegram_bot.py")
        return 1
    
    print(f"Токен бота: {settings.telegram_bot_token[:10]}...")
    
    # Создаем и запускаем бота с MCP поддержкой
    bot = TelegramMonitoringBot(settings.telegram_bot_token, use_mcp=True)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем")
    except Exception as e:
        print(f"Ошибка: {e}")
        return 1
    finally:
        await bot.close()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
