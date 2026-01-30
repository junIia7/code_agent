"""
Агент-разработчик: получает ТЗ и исправляет код
"""
import logging
from typing import Dict
from .base import AGNOAgent

logger = logging.getLogger('github-app')


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
