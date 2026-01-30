"""
Агент-аналитик: анализирует issue и создает техническое задание
"""
import os
import logging
from typing import Dict
from .base import AGNOAgent

logger = logging.getLogger('github-app')


class IssueAnalyzerAgent(AGNOAgent):
    """Агент-аналитик: анализирует issue и создает техническое задание"""
    
    def __init__(self):
        instructions = """Ты - опытный технический аналитик, который превращает описания проблем (issue) 
в четкие технические задания для программистов.

Твоя задача:
1. Проанализировать описание issue
2. Выделить ключевые требования
3. Определить технические детали
4. Создать структурированное ТЗ

Формат ТЗ должен включать:
- Цель задачи
- Описание проблемы/требования
- Технические требования
- Ожидаемый результат
- Критерии приемки (если возможно)
- Список файлов, которые нужно изменить (если возможно определить)

Будь конкретным и технически точным."""
        
        super().__init__(
            name="IssueAnalyzer",
            role="Technical Analyst",
            instructions=instructions
        )
    
    def process(self, input_data: Dict) -> Dict:
        """Анализирует issue и создает техническое задание"""
        try:
            issue_title = input_data.get('issue_title', '')
            issue_body = input_data.get('issue_body', '')
            repository_name = input_data.get('repository_name', '')
            
            # Формируем запрос для анализа
            prompt = f"""
РЕПОЗИТОРИЙ: {repository_name}

НАЗВАНИЕ ISSUE: {issue_title}

ОПИСАНИЕ ISSUE:
{issue_body if issue_body else 'Описание отсутствует'}

Проанализируй эту issue и создай подробное техническое задание для программиста.
"""
            
            logger.info(f"🤖 {self.name}: Анализирую issue...")
            logger.debug(f"📝 {self.name}: Промпт для анализа: {prompt[:200]}...")
            
            # Проверка наличия API ключа
            if not os.getenv('OPENAI_API_KEY'):
                raise ValueError("OPENAI_API_KEY не установлен. Установите API ключ в .env файле.")
            
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.instructions},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0
                )
                
                # Проверка ответа
                if not response.choices or len(response.choices) == 0:
                    raise ValueError("Модель не вернула ответ")
                
                if not response.choices[0].message or not response.choices[0].message.content:
                    raise ValueError("Ответ модели пуст")
                
                technical_spec = response.choices[0].message.content
                
                logger.info(f"✅ {self.name}: Техническое задание создано (длина: {len(technical_spec)} символов)")
                logger.debug(f"📋 {self.name}: ТЗ начало: {technical_spec[:200]}...")
                
            except Exception as api_error:
                logger.error(f"❌ {self.name}: Ошибка API: {str(api_error)}")
                raise
            
            return {
                'success': True,
                'technical_spec': technical_spec,
                'agent': self.name
            }
            
        except Exception as e:
            logger.error(f"❌ {self.name}: Ошибка при анализе - {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'agent': self.name
            }
