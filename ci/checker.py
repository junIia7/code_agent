"""
Проверка результатов CI
"""
import logging

logger = logging.getLogger('github-app')


def check_ci_results_match(ci_before, ci_after):
    """
    Проверяет, что результаты CI до и после изменений совпадают или улучшились
    
    Args:
        ci_before: Результаты CI до изменений
        ci_after: Результаты CI после изменений
        
    Returns:
        dict с результатом проверки
    """
    before_summary = ci_before.get('summary', {}) if ci_before else {}
    after_summary = ci_after.get('summary', {}) if ci_after else {}
    
    build_before = before_summary.get('build_passed')
    test_before = before_summary.get('test_passed')
    
    build_after = after_summary.get('build_passed')
    test_after = after_summary.get('test_passed')
    
    issues = []
    recommendations = []
    
    # Проверяем синтаксис (используется build_passed для обратной совместимости)
    if build_before is not None and build_after is not None:
        if build_before and not build_after:
            issues.append("Проверка синтаксиса проходила ДО изменений, но НЕ проходит ПОСЛЕ изменений")
            recommendations.append("Исправить синтаксические ошибки, чтобы восстановить работоспособность проекта")
        elif not build_before and build_after:
            # Это улучшение - проверка синтаксиса начала проходить
            pass
    
    # Проверяем тесты
    if test_before is not None and test_after is not None:
        if test_before and not test_after:
            issues.append("Тесты проходили ДО изменений, но НЕ проходят ПОСЛЕ изменений")
            recommendations.append("Исправить падающие тесты, чтобы восстановить работоспособность")
        elif not test_before and test_after:
            # Это улучшение - тесты начали проходить
            pass
    
    # Если есть проблемы - результаты не совпадают
    if issues:
        reason = "; ".join(issues)
        return {
            'match': False,
            'reason': reason,
            'issues': issues,
            'recommendations': recommendations
        }
    
    # Если все совпадает или улучшилось
    return {
        'match': True,
        'reason': 'Результаты CI совпадают или улучшились'
    }
