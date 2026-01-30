"""
GitHub App аутентификация
"""
import os
import jwt
import time
import logging
import requests
from .config import GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, GITHUB_APP_PRIVATE_KEY_PATH

logger = logging.getLogger('github-app')


def get_github_app_private_key():
    """
    Получает приватный ключ GitHub App из переменной окружения или файла
    
    Returns:
        str: Приватный ключ
    """
    # Сначала проверяем путь к файлу
    if GITHUB_APP_PRIVATE_KEY_PATH:
        try:
            # Очищаем путь от пробелов и кавычек
            key_path = GITHUB_APP_PRIVATE_KEY_PATH.strip().strip('"').strip("'")
            
            # Если путь относительный, делаем его относительно рабочей директории приложения
            if not os.path.isabs(key_path):
                # Получаем директорию, где находится main.py
                app_dir = os.path.dirname(os.path.abspath(__file__))
                # Поднимаемся на уровень выше (из github/ в корень)
                app_dir = os.path.dirname(app_dir)
                key_path = os.path.join(app_dir, key_path)
                # Нормализуем путь (убираем .. и .)
                key_path = os.path.normpath(key_path)
            
            logger.info(f"🔍 Проверка файла с приватным ключом: {key_path}")
            logger.info(f"📂 Рабочая директория: {os.getcwd()}")
            logger.info(f"📂 Директория приложения: {os.path.dirname(os.path.abspath(__file__))}")
            
            if os.path.exists(key_path):
                with open(key_path, 'r', encoding='utf-8') as f:
                    private_key = f.read()
                logger.info(f"✅ Приватный ключ загружен из файла: {key_path}")
                return private_key
            else:
                logger.warning(f"⚠️  Файл с приватным ключом не найден: {key_path}")
                logger.warning(f"⚠️  Проверьте, что путь указан правильно в .env файле")
        except Exception as e:
            logger.error(f"❌ Ошибка при чтении файла с приватным ключом: {str(e)}")
            import traceback
            logger.error(f"❌ Детали ошибки: {traceback.format_exc()}")
    
    # Если путь к файлу не указан или файл не найден, используем переменную окружения
    if GITHUB_APP_PRIVATE_KEY:
        return GITHUB_APP_PRIVATE_KEY
    
    return None


def get_github_app_token():
    """
    Генерирует JWT токен для GitHub App
    """
    if not GITHUB_APP_ID:
        raise ValueError("GITHUB_APP_ID должен быть установлен")
    
    # Получаем приватный ключ из переменной окружения или файла
    private_key = get_github_app_private_key()
    if not private_key:
        raise ValueError("GITHUB_APP_PRIVATE_KEY или GITHUB_APP_PRIVATE_KEY_PATH должны быть установлены")
    
    # Парсим приватный ключ (заменяем \n на переносы строк)
    private_key = private_key.replace('\\n', '\n')
    
    # Создаем JWT токен
    now = int(time.time())
    payload = {
        'iat': now - 60,  # Выдано 60 секунд назад
        'exp': now + 600,  # Истекает через 10 минут
        'iss': GITHUB_APP_ID
    }
    
    token = jwt.encode(payload, private_key, algorithm='RS256')
    return token


def get_installation_access_token(installation_id):
    """
    Получает access token для установки GitHub App
    """
    app_token = get_github_app_token()
    
    headers = {
        'Authorization': f'Bearer {app_token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    url = f'https://api.github.com/app/installations/{installation_id}/access_tokens'
    response = requests.post(url, headers=headers)
    
    if response.status_code == 201:
        return response.json()['token']
    else:
        raise Exception(f"Ошибка получения access token: {response.status_code} - {response.text}")


def find_installation_id_for_repo(owner, repo):
    """
    Автоматически находит installation_id для указанного репозитория
    
    Args:
        owner: Владелец репозитория
        repo: Название репозитория
        
    Returns:
        installation_id или None, если не найдено
    """
    try:
        if not GITHUB_APP_ID:
            logger.warning("⚠️  GITHUB_APP_ID не установлен, пропускаю поиск installation_id")
            return None
        
        # Проверяем наличие приватного ключа (из переменной или файла)
        private_key = get_github_app_private_key()
        if not private_key:
            logger.warning("⚠️  Приватный ключ GitHub App не найден (GITHUB_APP_PRIVATE_KEY или GITHUB_APP_PRIVATE_KEY_PATH), пропускаю поиск installation_id")
            return None
        
        app_token = get_github_app_token()
        headers = {
            'Authorization': f'Bearer {app_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        # Получаем список всех установок
        url = 'https://api.github.com/app/installations'
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            logger.warning(f"⚠️  Не удалось получить список установок: {response.status_code}")
            return None
        
        installations = response.json()
        
        # Проверяем каждую установку
        for installation in installations:
            installation_id = installation['id']
            
            try:
                # Получаем access token для этой установки
                access_token = get_installation_access_token(installation_id)
                
                # Проверяем доступ к репозиторию
                repo_headers = {
                    'Authorization': f'token {access_token}',
                    'Accept': 'application/vnd.github.v3+json'
                }
                repo_url = f'https://api.github.com/repos/{owner}/{repo}'
                repo_response = requests.get(repo_url, headers=repo_headers)
                
                if repo_response.status_code == 200:
                    logger.info(f"✅ Найдена установка #{installation_id} для репозитория {owner}/{repo}")
                    return installation_id
                    
            except Exception as e:
                # Пропускаем эту установку, если нет доступа
                continue
        
        logger.warning(f"⚠️  Не найдена установка для репозитория {owner}/{repo}")
        return None
        
    except Exception as e:
        logger.error(f"⚠️  Ошибка при поиске installation_id: {str(e)}")
        return None
