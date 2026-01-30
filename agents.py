"""
Система агентов на AGNO для анализа issue и исправления кода
"""
import os
import json
import re
import logging
from typing import Dict, Optional
from openai import OpenAI
import httpx

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
                temperature=0
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


class ReviewerAgent(AGNOAgent):
    """Агент-ревьюер: проверяет изменения и дает вердикт"""
    
    def __init__(self):
        instructions = """Ты - опытный code reviewer, который проверяет изменения в коде.

Твоя задача:
1. Изучить исходную задачу (issue)
2. Проанализировать техническое задание
3. Проверить внесенные изменения
4. Сравнить результаты CI до и после изменений
5. Дать вердикт: принимается решение или нет

Критерии принятия:
- ОБЯЗАТЕЛЬНО: Сборка проекта должна работать так же, как до изменений (или лучше)
- ОБЯЗАТЕЛЬНО: Тесты должны проходить так же, как до изменений (или лучше)
- ОПЦИОНАЛЬНО: Качество кода не должно ухудшиться (но это не решающий фактор)

Если изменения не соответствуют критериям, ты должен:
- Четко описать проблему
- Указать, что именно не работает
- Дать рекомендации по исправлению

Формат ответа должен быть JSON:
{
    "approved": true/false,
    "reason": "краткое объяснение вердикта",
    "issues": ["список проблем, если есть"],
    "recommendations": ["рекомендации по исправлению, если есть"]
}"""
        
        super().__init__(
            name="Reviewer",
            role="Code Reviewer",
            instructions=instructions
        )
    
    def process(self, input_data: Dict) -> Dict:
        """Проверяет изменения и дает вердикт"""
        try:
            issue_title = input_data.get('issue_title', '')
            issue_body = input_data.get('issue_body', '')
            technical_spec = input_data.get('technical_spec', '')
            changed_files = input_data.get('changed_files', [])
            ci_before = input_data.get('ci_before', {})
            ci_after = input_data.get('ci_after', {})
            repository_name = input_data.get('repository_name', '')
            
            # Формируем запрос для проверки
            prompt = f"""
РЕПОЗИТОРИЙ: {repository_name}

ИСХОДНАЯ ЗАДАЧА:
Название: {issue_title}
Описание: {issue_body}

ТЕХНИЧЕСКОЕ ЗАДАНИЕ:
{technical_spec}

ИЗМЕНЕННЫЕ ФАЙЛЫ:
{', '.join(changed_files) if changed_files else 'Не указаны'}

РЕЗУЛЬТАТЫ CI ДО ИЗМЕНЕНИЙ:
Сборка: {'✅ Успешно' if ci_before.get('summary', {}).get('build_passed') else '❌ Ошибка'}
Тесты: {'✅ Успешно' if ci_before.get('summary', {}).get('test_passed') else '❌ Ошибка'}
Качество: {'✅ Успешно' if ci_before.get('summary', {}).get('quality_passed') else '⚠️ Предупреждения' if ci_before.get('summary', {}).get('quality_passed') is False else 'Не проверялось'}

РЕЗУЛЬТАТЫ CI ПОСЛЕ ИЗМЕНЕНИЙ:
Сборка: {'✅ Успешно' if ci_after.get('summary', {}).get('build_passed') else '❌ Ошибка'}
Тесты: {'✅ Успешно' if ci_after.get('summary', {}).get('test_passed') else '❌ Ошибка'}
Качество: {'✅ Успешно' if ci_after.get('summary', {}).get('quality_passed') else '⚠️ Предупреждения' if ci_after.get('summary', {}).get('quality_passed') is False else 'Не проверялось'}

ДЕТАЛИ ОШИБОК (если есть):
{self._format_ci_details(ci_after)}

Проверь изменения и дай вердикт. Отвечай ТОЛЬКО JSON объектом в указанном формате.
"""
            
            logger.info(f"🤖 {self.name}: Проверяю изменения...")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.instructions},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )
            
            review_text = response.choices[0].message.content.strip()
            
            # Извлекаем JSON
            if "```json" in review_text:
                review_text = review_text.split("```json")[1].split("```")[0].strip()
            elif "```" in review_text:
                review_text = review_text.split("```")[1].split("```")[0].strip()
            
            try:
                review_result = json.loads(review_text)
                logger.info(f"✅ {self.name}: Вердикт - {'✅ Одобрено' if review_result.get('approved') else '❌ Отклонено'}")
                return {
                    'success': True,
                    'approved': review_result.get('approved', False),
                    'reason': review_result.get('reason', ''),
                    'issues': review_result.get('issues', []),
                    'recommendations': review_result.get('recommendations', []),
                    'agent': self.name
                }
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Не удалось распарсить JSON ответ ревьюера: {e}")
                # Пытаемся определить вердикт по тексту
                approved = 'approved' in review_text.lower() or 'принято' in review_text.lower() or 'одобрено' in review_text.lower()
                return {
                    'success': True,
                    'approved': approved,
                    'reason': review_text[:500],
                    'issues': [],
                    'recommendations': [],
                    'agent': self.name
                }
            
        except Exception as e:
            logger.error(f"❌ {self.name}: Ошибка при проверке - {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'approved': False,
                'agent': self.name
            }
    
    def _format_ci_details(self, ci_results):
        """Форматирует детали результатов CI для промпта"""
        if not ci_results or not ci_results.get('results'):
            return "Нет деталей"
        
        details = []
        results = ci_results.get('results', {})
        
        if not results.get('build', {}).get('success'):
            details.append(f"Ошибка сборки:\n{results['build'].get('error', '')[:500]}")
        
        if not results.get('test', {}).get('success'):
            details.append(f"Ошибка тестов:\n{results['test'].get('error', '')[:500]}")
        
        return "\n\n".join(details) if details else "Все проверки прошли успешно"


class AGNOAgentSystem:
    """Система управления агентами AGNO"""
    
    def __init__(self):
        self.analyzer = IssueAnalyzerAgent()
        self.developer = CodeDeveloperAgent()
        self.reviewer = ReviewerAgent()
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
    
    def review_changes(self, issue_title: str, issue_body: str, technical_spec: str, 
                      changed_files: list, ci_before: Dict, ci_after: Dict, repository_name: str) -> Dict:
        """Проверяет изменения через агента-ревьюера"""
        input_data = {
            'issue_title': issue_title,
            'issue_body': issue_body,
            'technical_spec': technical_spec,
            'changed_files': changed_files,
            'ci_before': ci_before,
            'ci_after': ci_after,
            'repository_name': repository_name
        }
        return self.reviewer.process(input_data)
    
    def determine_files_to_change(self, technical_spec: str, repository_name: str) -> Dict:
        """Определяет список файлов, которые нужно изменить на основе ТЗ"""
        try:
            prompt = f"""
РЕПОЗИТОРИЙ: {repository_name}

ТЕХНИЧЕСКОЕ ЗАДАНИЕ:
{technical_spec}

Проанализируй техническое задание и определи, какие файлы нужно изменить или создать.
Верни список путей к файлам в формате JSON массива, например: ["file1.py", "src/file2.py"]
Если файлы невозможно определить точно, верни пустой массив [].
Отвечай ТОЛЬКО JSON массивом, без дополнительных комментариев.
"""
            
            logger.info(f"🔍 Определяю файлы для изменения на основе ТЗ...")
            
            response = self.analyzer.client.chat.completions.create(
                model=self.analyzer.model,
                messages=[
                    {"role": "system", "content": "Ты помощник, который анализирует технические задания и определяет список файлов для изменения. Отвечай только JSON массивом путей к файлам."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )
            
            files_text = response.choices[0].message.content.strip()
            
            # Пытаемся извлечь JSON массив
            # Убираем markdown код блоки, если есть
            if "```json" in files_text:
                files_text = files_text.split("```json")[1].split("```")[0].strip()
            elif "```" in files_text:
                files_text = files_text.split("```")[1].split("```")[0].strip()
            
            try:
                files_list = json.loads(files_text)
                if isinstance(files_list, list):
                    # Фильтруем только строки (пути к файлам)
                    files_list = [f for f in files_list if isinstance(f, str) and f.strip()]
                    logger.info(f"✅ Определено {len(files_list)} файлов для изменения: {files_list}")
                    return {
                        'success': True,
                        'files': files_list
                    }
                else:
                    logger.warning(f"⚠️ Ответ не является массивом: {files_list}")
                    return {
                        'success': True,
                        'files': []
                    }
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Не удалось распарсить JSON: {e}. Ответ: {files_text}")
                # Пытаемся извлечь пути к файлам через регулярные выражения
                # Ищем пути к файлам (например, "file.py", "src/file.py", "./file.py")
                file_pattern = r'["\']([^"\']+\.(py|js|ts|java|cpp|c|h|go|rs|php|rb|yml|yaml|json|md|txt|html|css|jsx|tsx))["\']'
                matches = re.findall(file_pattern, files_text)
                files_list = [match[0] for match in matches]
                if files_list:
                    logger.info(f"✅ Извлечено {len(files_list)} файлов через regex: {files_list}")
                    return {
                        'success': True,
                        'files': files_list
                    }
                return {
                    'success': True,
                    'files': []
                }
            
        except Exception as e:
            logger.error(f"❌ Ошибка при определении файлов: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'files': []
            }