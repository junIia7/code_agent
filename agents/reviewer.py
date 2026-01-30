"""
Агент-ревьюер: проверяет изменения и дает вердикт
"""
import json
import logging
from typing import Dict
from .base import AGNOAgent

logger = logging.getLogger('github-app')


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

КРИТИЧЕСКИ ВАЖНЫЕ КРИТЕРИИ ПРИНЯТИЯ (ОБЯЗАТЕЛЬНЫЕ):
- РЕЗУЛЬТАТЫ CI ДО И ПОСЛЕ ИЗМЕНЕНИЙ ДОЛЖНЫ СОВПАДАТЬ:
  * Если проверка синтаксиса проходила ДО изменений - она ДОЛЖНА проходить и ПОСЛЕ
  * Если проверка синтаксиса НЕ проходила ДО изменений - она МОЖЕТ не проходить и ПОСЛЕ (но лучше исправить)
  * Если тесты проходили ДО изменений - они ДОЛЖНЫ проходить и ПОСЛЕ
  * Если тесты НЕ проходили ДО изменений - они МОЖУТ не проходить и ПОСЛЕ (но лучше исправить)
  
- ЗАПРЕЩЕНО одобрять изменения, если:
  * Проверка синтаксиса проходила ДО, но НЕ проходит ПОСЛЕ - ОТКЛОНИТЬ
  * Тесты проходили ДО, но НЕ проходят ПОСЛЕ - ОТКЛОНИТЬ
  * Любое ухудшение состояния CI - ОТКЛОНИТЬ

ВАЖНО: 
- Результаты CI до и после должны быть ИДЕНТИЧНЫМИ или ЛУЧШЕ. 
- Если состояние CI ухудшилось - ОБЯЗАТЕЛЬНО отклонить изменения.
- КАЧЕСТВО КОДА НЕ УЧИТЫВАЕТСЯ в критериях принятия - только синтаксис и тесты!

Если изменения не соответствуют критериям, ты должен:
- Четко описать проблему
- Указать, что именно не работает
- Указать, как изменились результаты CI
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
            
            # Формируем детальное сравнение CI
            ci_comparison = self._format_ci_comparison(ci_before, ci_after)
            
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

{ci_comparison}

ДЕТАЛИ ОШИБОК ПОСЛЕ ИЗМЕНЕНИЙ (если есть):
{self._format_ci_details(ci_after)}

КРИТИЧЕСКИ ВАЖНО: 
Сравни результаты CI ДО и ПОСЛЕ изменений. 
Результаты ДОЛЖНЫ совпадать или быть лучше. 
Если проверка синтаксиса/тесты проходили ДО, но НЕ проходят ПОСЛЕ - ОБЯЗАТЕЛЬНО отклони изменения.

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
    
    def _format_ci_comparison(self, ci_before, ci_after):
        """Форматирует сравнение результатов CI до и после изменений"""
        before_summary = ci_before.get('summary', {}) if ci_before else {}
        after_summary = ci_after.get('summary', {}) if ci_after else {}
        
        build_before = before_summary.get('build_passed')
        test_before = before_summary.get('test_passed')
        quality_before = before_summary.get('quality_passed')
        
        build_after = after_summary.get('build_passed')
        test_after = after_summary.get('test_passed')
        quality_after = after_summary.get('quality_passed')
        
        # Форматируем статусы
        def format_status(status, label):
            if status is True:
                return f"{label}: ✅ Успешно"
            elif status is False:
                return f"{label}: ❌ Ошибка"
            else:
                return f"{label}: ⚪ Не проверялось"
        
        # Определяем изменения
        build_change = ""
        test_change = ""
        
        if build_before is not None and build_after is not None:
            if build_before and not build_after:
                build_change = " ⚠️ УХУДШЕНИЕ: проверка синтаксиса проходила ДО, но НЕ проходит ПОСЛЕ - ОТКЛОНИТЬ!"
            elif not build_before and build_after:
                build_change = " ✅ УЛУЧШЕНИЕ: проверка синтаксиса не проходила ДО, но проходит ПОСЛЕ"
            elif build_before == build_after:
                build_change = " ✅ Без изменений"
            else:
                build_change = " ⚠️ Изменение состояния"
        
        if test_before is not None and test_after is not None:
            if test_before and not test_after:
                test_change = " ⚠️ УХУДШЕНИЕ: тесты проходили ДО, но НЕ проходят ПОСЛЕ - ОТКЛОНИТЬ!"
            elif not test_before and test_after:
                test_change = " ✅ УЛУЧШЕНИЕ: тесты не проходили ДО, но проходят ПОСЛЕ"
            elif test_before == test_after:
                test_change = " ✅ Без изменений"
            else:
                test_change = " ⚠️ Изменение состояния"
        
        comparison = f"""
═══════════════════════════════════════════════════════════════
СРАВНЕНИЕ РЕЗУЛЬТАТОВ CI ДО И ПОСЛЕ ИЗМЕНЕНИЙ
═══════════════════════════════════════════════════════════════

РЕЗУЛЬТАТЫ CI ДО ИЗМЕНЕНИЙ:
{format_status(build_before, 'Проверка синтаксиса')}
{format_status(test_before, 'Тесты')}

РЕЗУЛЬТАТЫ CI ПОСЛЕ ИЗМЕНЕНИЙ:
{format_status(build_after, 'Проверка синтаксиса')}{build_change}
{format_status(test_after, 'Тесты')}{test_change}

═══════════════════════════════════════════════════════════════
КРИТИЧЕСКОЕ ПРАВИЛО: Результаты CI ДО и ПОСЛЕ должны СОВПАДАТЬ или быть ЛУЧШЕ.
Если проверка синтаксиса/тесты проходили ДО, но НЕ проходят ПОСЛЕ - ОБЯЗАТЕЛЬНО отклони!

ВАЖНО: Качество кода НЕ учитывается в критериях принятия. Только синтаксис и тесты!
═══════════════════════════════════════════════════════════════
"""
        return comparison
    
    def _format_ci_details(self, ci_results):
        """Форматирует детали результатов CI для промпта"""
        if not ci_results or not ci_results.get('results'):
            return "Нет деталей"
        
        details = []
        results = ci_results.get('results', {})
        
        if not results.get('build', {}).get('success'):
            details.append(f"Ошибка проверки синтаксиса:\n{results['build'].get('error', '')[:500]}")
        
        if not results.get('test', {}).get('success'):
            details.append(f"Ошибка тестов:\n{results['test'].get('error', '')[:500]}")
        
        return "\n\n".join(details) if details else "Все проверки прошли успешно"
