"""
Система агентов на AGNO для анализа issue и исправления кода
"""
import os
import logging
from typing import Dict, Optional
from openai import OpenAI

logger = logging.getLogger('github-app')

class AGNOAgent:
    """Базовый класс для AGNO агентов"""
    
    def __init__(self, name: str, role: str, instructions: str):
        self.name = name
        self.role = role
        self.instructions = instructions
        
        # Поддержка DeepSeek и других OpenAI-совместимых API
        api_key = os.getenv('OPENAI_API_KEY')
        base_url = os.getenv('OPENAI_BASE_URL')
        
        # Если base_url не указан, но ключ похож на DeepSeek, используем DeepSeek endpoint
        if not base_url and api_key:
            # DeepSeek ключи обычно начинаются с 'sk-' и имеют определенную длину
            # Но лучше проверить через переменную окружения
            if os.getenv('USE_DEEPSEEK', '').lower() in ('true', '1', 'yes'):
                base_url = 'https://api.deepseek.com'
        
        # Создаем клиент с поддержкой кастомного base_url
        client_kwargs = {'api_key': api_key}
        if base_url:
            client_kwargs['base_url'] = base_url
        
        self.client = OpenAI(**client_kwargs)
        
        # Модель по умолчанию зависит от провайдера
        default_model = 'gpt-4o-mini' if not base_url or 'deepseek' not in base_url.lower() else 'deepseek-chat'
        self.model = os.getenv('OPENAI_MODEL', default_model)
    
    def process(self, input_data: Dict) -> Dict:
        """Обрабатывает входные данные и возвращает результат"""
        raise NotImplementedError("Subclasses must implement process method")


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
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.instructions},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            technical_spec = response.choices[0].message.content
            
            logger.info(f"✅ {self.name}: Техническое задание создано")
            
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


class CodeDeveloperAgent(AGNOAgent):
    """Агент-разработчик: получает ТЗ и исправляет код"""
    
    def __init__(self):
        instructions = """Ты - опытный программист, который исправляет код на основе технического задания.

Твоя задача:
1. Изучить техническое задание
2. Проанализировать текущий код
3. Внести необходимые изменения
4. Обеспечить, чтобы код соответствовал требованиям ТЗ

Ты должен:
- Писать чистый, читаемый код
- Следовать лучшим практикам программирования
- Сохранять существующую структуру кода, если это возможно
- Добавлять комментарии
- Убедиться, что изменения решают проблему из ТЗ

Формат ответа:
- Полный измененный код файла
- Краткое описание внесенных изменений
- Объяснение, почему эти изменения решают проблему"""
        
        super().__init__(
            name="CodeDeveloper",
            role="Software Developer",
            instructions=instructions
        )
    
    def process(self, input_data: Dict) -> Dict:
        """Исправляет код на основе технического задания"""
        try:
            technical_spec = input_data.get('technical_spec', '')
            file_path = input_data.get('file_path', '')
            current_code = input_data.get('current_code', '')
            repository_name = input_data.get('repository_name', '')
            
            if not technical_spec:
                return {
                    'success': False,
                    'error': 'Техническое задание отсутствует',
                    'agent': self.name
                }
            
            # Формируем запрос для исправления кода
            prompt = f"""
РЕПОЗИТОРИЙ: {repository_name}
ФАЙЛ: {file_path}

ТЕХНИЧЕСКОЕ ЗАДАНИЕ:
{technical_spec}

ТЕКУЩИЙ КОД ФАЙЛА:
```python
{current_code}
```

Исправь код согласно техническому заданию. Верни полный исправленный код файла.
"""
            
            logger.info(f"🤖 {self.name}: Исправляю код файла {file_path}...")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.instructions},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2
            )
            
            fixed_code = response.choices[0].message.content
            
            # Извлекаем код из markdown блока, если он есть
            if "```python" in fixed_code:
                fixed_code = fixed_code.split("```python")[1].split("```")[0].strip()
            elif "```" in fixed_code:
                fixed_code = fixed_code.split("```")[1].split("```")[0].strip()
            
            logger.info(f"✅ {self.name}: Код исправлен для файла {file_path}")
            
            return {
                'success': True,
                'fixed_code': fixed_code,
                'file_path': file_path,
                'agent': self.name
            }
            
        except Exception as e:
            logger.error(f"❌ {self.name}: Ошибка при исправлении кода - {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'agent': self.name
            }


class AGNOAgentSystem:
    """Система управления агентами AGNO"""
    
    def __init__(self):
        self.analyzer = IssueAnalyzerAgent()
        self.developer = CodeDeveloperAgent()
        logger.info("🚀 Система AGNO агентов инициализирована")
    
    def analyze_issue(self, issue_title: str, issue_body: str, repository_name: str) -> Dict:
        """Анализирует issue через агента-аналитика"""
        input_data = {
            'issue_title': issue_title,
            'issue_body': issue_body,
            'repository_name': repository_name
        }
        return self.analyzer.process(input_data)
    
    def fix_code(self, technical_spec: str, file_path: str, current_code: str, repository_name: str) -> Dict:
        """Исправляет код через агента-разработчика"""
        input_data = {
            'technical_spec': technical_spec,
            'file_path': file_path,
            'current_code': current_code,
            'repository_name': repository_name
        }
        return self.developer.process(input_data)
