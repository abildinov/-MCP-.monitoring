#!/usr/bin/env python3
"""
Единый скрипт запуска MCP системы мониторинга
Запускает MCP сервер (SSE режим) и Telegram бота
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path


async def main():
    """Главная функция запуска системы"""
    print("Запуск единой MCP системы мониторинга...")
    print("=" * 60)
    
    # Проверяем, что мы в правильной директории
    current_dir = Path.cwd()
    if not (current_dir / "mcp-server").exists():
        print("Ошибка: Запустите скрипт из корневой директории проекта")
        print(f"Текущая директория: {current_dir}")
        return 1
    
    processes = []
    
    try:
        # 1. Запускаем MCP сервер в HTTP режиме
        print("\n1. Запуск MCP сервера (HTTP режим)...")
        mcp_cmd = [
            sys.executable, 
            "mcp-server/server.py", 
            "--transport", "http"
        ]
        
        mcp_process = subprocess.Popen(
            mcp_cmd,
            cwd=current_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        processes.append(("MCP Server", mcp_process))
        
        print(f"MCP сервер запущен (PID: {mcp_process.pid})")
        print("   URL: http://localhost:3000")
        
        # Ждем запуска MCP сервера
        print("Ожидание запуска MCP сервера...")
        await asyncio.sleep(5)
        
        # Проверяем, что MCP сервер запустился
        if mcp_process.poll() is not None:
            print("MCP сервер завершился с ошибкой!")
            stdout, stderr = mcp_process.communicate()
            print(f"STDOUT: {stdout}")
            print(f"STDERR: {stderr}")
            return 1
        
        # 2. Запускаем Telegram бота
        print("\n2. Запуск Telegram бота...")
        telegram_cmd = [sys.executable, "scripts/start_telegram_bot.py"]
        
        telegram_process = subprocess.Popen(
            telegram_cmd,
            cwd=current_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        processes.append(("Telegram Bot", telegram_process))
        
        print(f"Telegram бот запущен (PID: {telegram_process.pid})")
        
        # Ждем запуска Telegram бота
        print("Ожидание запуска Telegram бота...")
        await asyncio.sleep(3)
        
        # Проверяем, что Telegram бот запустился
        if telegram_process.poll() is not None:
            print("Telegram бот завершился с ошибкой!")
            stdout, stderr = telegram_process.communicate()
            print(f"STDOUT: {stdout}")
            print(f"STDERR: {stderr}")
            return 1
        
        # 3. Система готова
        print("\n" + "=" * 60)
        print("СИСТЕМА ГОТОВА К РАБОТЕ!")
        print("=" * 60)
        print()
        print("Доступные интерфейсы:")
        print("   • MCP Сервер: http://localhost:3000 (HTTP API)")
        print("   • Telegram Бот: Активен")
        print("   • Claude Desktop: Используйте claude_desktop_config.json")
        print()
        print("Команды для тестирования:")
        print("   • Telegram: /start -> /analyze")
        print("   • Claude Desktop: 'Покажи загрузку CPU'")
        print()
        print("Для остановки нажмите Ctrl+C")
        print("=" * 60)
        
        # Мониторим процессы
        while True:
            await asyncio.sleep(5)
            
            # Проверяем статус процессов
            for name, process in processes:
                if process.poll() is not None:
                    print(f"{name} завершился неожиданно!")
                    stdout, stderr = process.communicate()
                    print(f"STDOUT: {stdout}")
                    print(f"STDERR: {stderr}")
                    return 1
    
    except KeyboardInterrupt:
        print("\nПолучен сигнал остановки...")
    
    except Exception as e:
        print(f"Критическая ошибка: {e}")
        return 1
    
    finally:
        # Останавливаем все процессы
        print("\nОстановка процессов...")
        for name, process in processes:
            if process.poll() is None:
                print(f"Остановка {name}...")
                process.terminate()
                
                # Ждем graceful shutdown
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print(f"Принудительное завершение {name}...")
                    process.kill()
        
        print("Все процессы остановлены")
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 До свидания!")
        sys.exit(0)
