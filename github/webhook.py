"""
GitHub Webhook функции
"""
import re
import hmac
import hashlib
import logging
from .config import WEBHOOK_SECRET

logger = logging.getLogger('github-app')


def verify_webhook_signature(payload_body, signature_header):
    """
    Проверяет подпись webhook от GitHub используя HMAC SHA256
    """
    if not WEBHOOK_SECRET:
        logger.warning("⚠️  ВНИМАНИЕ: WEBHOOK_SECRET не установлен, проверка подписи пропущена")
        return True  # Если секрет не установлен, пропускаем проверку
    
    if not signature_header:
        return False
    
    # GitHub отправляет подпись в формате "sha256=..."
    if not signature_header.startswith('sha256='):
        return False
    
    # Извлекаем хеш из заголовка
    received_hash = signature_header.split('=')[1]
    
    # Вычисляем ожидаемый хеш
    expected_hash = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        payload_body,
        hashlib.sha256
    ).hexdigest()
    
    # Безопасное сравнение хешей
    return hmac.compare_digest(received_hash, expected_hash)


def parse_github_url(url):
    """
    Парсит GitHub URL и извлекает owner, repo и issue number
    
    Args:
        url: GitHub URL (репозиторий или issue)
        
    Returns:
        dict с owner, repo, issue_number (если есть)
    """
    # Паттерны для разных форматов GitHub URL
    patterns = [
        r'github\.com/([^/]+)/([^/]+)/issues/(\d+)',  # issue URL
        r'github\.com/([^/]+)/([^/]+)',  # repo URL
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            owner = match.group(1)
            repo = match.group(2)
            issue_number = match.group(3) if len(match.groups()) > 2 else None
            return {
                'owner': owner,
                'repo': repo,
                'issue_number': issue_number
            }
    
    raise ValueError(f"Неверный формат GitHub URL: {url}")
