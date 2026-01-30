"""
Система управления агентами AGNO
"""
import json
import re
import logging
from typing import Dict
from .analyzer import IssueAnalyzerAgent
from .developer import CodeDeveloperAgent
from .reviewer import ReviewerAgent

logger = logging.getLogger('github-app')


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
