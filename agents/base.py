"""
Базовый класс для AGNO агентов
"""
import os
import logging
import httpx
from typing import Dict
from openai import OpenAI

logger = logging.getLogger('github-app')


class AGNOAgent:
    """Базовый класс для AGNO агентов"""
    
    def __init__(self, name: str, role: str, instructions: str):
        self.name = name
        self.role = role
        self.instructions = instructions
        
        # Поддержка OpenAI, DeepSeek, OpenRouter и других OpenAI-совместимых API
        api_key = os.getenv('OPENAI_API_KEY')
        base_url = os.getenv('OPENAI_BASE_URL', '').strip()
        
        # Проверка наличия API ключа
        if not api_key:
            logger.warning(f"⚠️  {name}: OPENAI_API_KEY не установлен")
        
        # Если base_url не указан, проверяем автоматические настройки
        if not base_url and api_key:
            # Проверяем USE_DEEPSEEK
            if os.getenv('USE_DEEPSEEK', '').lower() in ('true', '1', 'yes'):
                base_url = 'https://api.deepseek.com'
                logger.info(f"🔧 {name}: Используется DeepSeek API")
            # Проверяем USE_OPENROUTER
            elif os.getenv('USE_OPENROUTER', '').lower() in ('true', '1', 'yes'):
                base_url = 'https://openrouter.ai/api/v1'
                logger.info(f"🔧 {name}: Используется OpenRouter API")
        
        # Создаем клиент с поддержкой кастомного base_url
        client_kwargs = {'api_key': api_key}
        if base_url:
            client_kwargs['base_url'] = base_url
            logger.info(f"🔧 {name}: Base URL установлен: {base_url}")
        
        # OpenRouter требует HTTP-Referer заголовок (опционально, но рекомендуется)
        http_referer = None
        if base_url and 'openrouter' in base_url.lower():
            http_referer = os.getenv('OPENROUTER_HTTP_REFERER', '')
            if http_referer:
                logger.info(f"🔧 {name}: OpenRouter HTTP-Referer: {http_referer}")
        
        try:
            # Для OpenRouter добавляем кастомные заголовки через httpx клиент
            if base_url and 'openrouter' in base_url.lower():
                # Создаем httpx клиент с кастомными заголовками для OpenRouter
                headers = {}
                if http_referer:
                    headers['HTTP-Referer'] = http_referer
                headers['X-Title'] = 'GitHub Issue Analyzer Agent'
                
                http_client = httpx.Client(headers=headers)
                client_kwargs['http_client'] = http_client
                logger.info(f"🔧 {name}: Настроен HTTP клиент с заголовками для OpenRouter")
            
            self.client = OpenAI(**client_kwargs)
        except Exception as e:
            logger.error(f"❌ {name}: Ошибка при создании OpenAI клиента: {str(e)}")
            raise
        
        # Модель по умолчанию зависит от провайдера
        if base_url and 'deepseek' in base_url.lower():
            default_model = 'deepseek-chat'
        elif base_url and 'openrouter' in base_url.lower():
            # OpenRouter использует формат provider/model, по умолчанию OpenAI модель
            default_model = 'openai/gpt-4o-mini'
        else:
            default_model = 'gpt-4o-mini'
        
        self.model = os.getenv('OPENAI_MODEL', default_model)
        logger.info(f"🤖 {name}: Используется модель {self.model}")
    
    def process(self, input_data: Dict) -> Dict:
        """Обрабатывает входные данные и возвращает результат"""
        raise NotImplementedError("Subclasses must implement process method")
