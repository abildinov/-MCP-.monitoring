"""
Интеграция с DeepSeek V3.1 через TimeWeb Cloud AI
"""

from .deepseek_client import DeepSeekClient
from .universal_client import UniversalLLMClient

__all__ = ["DeepSeekClient", "UniversalLLMClient"]

