import os
import sys
import jwt
import time
import hmac
import hashlib
import re
import base64
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv
from agents import AGNOAgentSystem

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout,
    force=True  # Переопределяем существующую конфигурацию
)

# Создаем логгер для приложения
logger = logging.getLogger('github-app')
logger.setLevel(logging.INFO)

# Настройка Flask логирования
logging.getLogger('werkzeug').setLevel(logging.INFO)

app = Flask(__name__)

# Инициализация системы AGNO агентов
agno_system = AGNOAgentSystem()

# Конфигурация GitHub App
GITHUB_APP_ID = os.getenv('GITHUB_APP_ID')
GITHUB_APP_PRIVATE_KEY = os.getenv('GITHUB_APP_PRIVATE_KEY')
GITHUB_APP_PRIVATE_KEY_PATH = os.getenv('GITHUB_APP_PRIVATE_KEY_PATH')
GITHUB_INSTALLATION_ID = os.getenv('GITHUB_INSTALLATION_ID', '')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')

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

def get_issue_data(owner, repo, issue_number, installation_id=None):
    """
    Получает данные issue через GitHub API
    
    Args:
        owner: Владелец репозитория
        repo: Название репозитория
        issue_number: Номер issue
        installation_id: ID установки GitHub App (опционально)
        
    Returns:
        dict с данными issue
    """
    if installation_id:
        access_token = get_installation_access_token(installation_id)
        headers = {
            'Authorization': f'token {access_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
    else:
        # Альтернативный способ: использование личного токена
        personal_token = os.getenv('GITHUB_TOKEN')
        if not personal_token:
            raise ValueError("Необходим либо GITHUB_INSTALLATION_ID, либо GITHUB_TOKEN")
        headers = {
            'Authorization': f'token {personal_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
    
    url = f'https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}'
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        issue_data = response.json()
        return {
            'number': issue_data['number'],
            'title': issue_data['title'],
            'body': issue_data.get('body', ''),
            'state': issue_data['state'],
            'url': issue_data['html_url'],
            'created_at': issue_data['created_at'],
            'user': issue_data['user']['login']
        }
    else:
        raise Exception(f"Ошибка получения issue: {response.status_code} - {response.text}")

def auto_fix_and_create_pr(owner, repo, issue_number, technical_spec, installation_id=None):
    """
    Автоматически определяет файлы для изменения, исправляет код и создает PR
    
    Args:
        owner: Владелец репозитория
        repo: Название репозитория
        issue_number: Номер issue
        technical_spec: Техническое задание
        installation_id: ID установки GitHub App (опционально)
        
    Returns:
        dict с информацией о созданном PR или ошибке
    """
    try:
        repo_full_name = f"{owner}/{repo}"
        
        # 1. Определяем файлы для изменения
        logger.info("🔍 Определяю файлы для изменения на основе ТЗ...")
        files_result = agno_system.determine_files_to_change(technical_spec, repo_full_name)
        
        if not files_result.get('success'):
            logger.error(f"❌ Ошибка при определении файлов: {files_result.get('error')}")
            return {
                'success': False,
                'error': f"Не удалось определить файлы: {files_result.get('error')}"
            }
        
        files_to_change = files_result.get('files', [])
        
        if not files_to_change:
            logger.warning("⚠️ Не удалось определить файлы для изменения. Пропускаю автоматическое исправление.")
            return {
                'success': False,
                'error': 'Не удалось определить файлы для изменения из технического задания',
                'technical_spec': technical_spec
            }
        
        logger.info(f"📋 Найдено {len(files_to_change)} файлов для изменения: {files_to_change}")
        
        # 2. Получаем access token
        if installation_id:
            access_token = get_installation_access_token(installation_id)
            headers = {
                'Authorization': f'token {access_token}',
                'Accept': 'application/vnd.github.v3+json'
            }
        else:
            personal_token = os.getenv('GITHUB_TOKEN')
            if not personal_token:
                raise ValueError("Необходим либо GITHUB_INSTALLATION_ID, либо GITHUB_TOKEN")
            headers = {
                'Authorization': f'token {personal_token}',
                'Accept': 'application/vnd.github.v3+json'
            }
        
        # 3. Получаем информацию о репозитории
        repo_url = f'https://api.github.com/repos/{owner}/{repo}'
        repo_response = requests.get(repo_url, headers=headers)
        
        if repo_response.status_code != 200:
            raise Exception(f"Не удалось получить информацию о репозитории: {repo_response.status_code}")
        
        repo_data = repo_response.json()
        default_branch = repo_data.get('default_branch', 'main')
        
        # 4. Создаем имя ветки
        branch_name = f"fix/issue-{issue_number}"
        if len(branch_name) > 200:
            branch_name = branch_name[:200]
        
        logger.info(f"🌿 Создание ветки {branch_name}...")
        
        # 5. Получаем SHA последнего коммита в основной ветке
        ref_url = f'https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{default_branch}'
        ref_response = requests.get(ref_url, headers=headers)
        
        if ref_response.status_code != 200:
            raise Exception(f"Не удалось получить информацию о ветке {default_branch}: {ref_response.status_code}")
        
        base_sha = ref_response.json()['object']['sha']
        
        # 6. Создаем новую ветку
        create_branch_url = f'https://api.github.com/repos/{owner}/{repo}/git/refs'
        branch_data = {
            'ref': f'refs/heads/{branch_name}',
            'sha': base_sha
        }
        branch_response = requests.post(create_branch_url, headers=headers, json=branch_data)
        
        if branch_response.status_code not in [201, 422]:
            if branch_response.status_code == 422:
                # Ветка уже существует, получаем её SHA
                existing_branch_url = f'https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{branch_name}'
                existing_response = requests.get(existing_branch_url, headers=headers)
                if existing_response.status_code == 200:
                    base_sha = existing_response.json()['object']['sha']
                    logger.info(f"ℹ️  Ветка {branch_name} уже существует, используем её")
                else:
                    raise Exception(f"Ветка существует, но не удалось получить её SHA: {existing_response.status_code}")
            else:
                raise Exception(f"Не удалось создать ветку: {branch_response.status_code} - {branch_response.text}")
        else:
            logger.info(f"✅ Ветка {branch_name} создана")
        
        # 7. Для каждого файла получаем код, исправляем и обновляем
        fixed_files = []
        failed_files = []
        
        for file_path in files_to_change:
            try:
                logger.info(f"📥 Получение кода файла {file_path}...")
                
                # Получаем содержимое файла
                file_url = f'https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={default_branch}'
                file_response = requests.get(file_url, headers=headers)
                
                if file_response.status_code != 200:
                    logger.warning(f"⚠️ Не удалось получить файл {file_path}: {file_response.status_code}")
                    failed_files.append({'file': file_path, 'error': f'Не удалось получить файл: {file_response.status_code}'})
                    continue
                
                file_data = file_response.json()
                current_code = base64.b64decode(file_data['content']).decode('utf-8')
                
                # Исправляем код через агента-разработчика
                logger.info(f"🔧 Исправление кода файла {file_path}...")
                fix_result = agno_system.fix_code(
                    technical_spec=technical_spec,
                    file_path=file_path,
                    current_code=current_code,
                    repository_name=repo_full_name
                )
                
                if not fix_result.get('success'):
                    logger.error(f"❌ Ошибка при исправлении файла {file_path}: {fix_result.get('error')}")
                    failed_files.append({'file': file_path, 'error': fix_result.get('error')})
                    continue
                
                fixed_code = fix_result.get('fixed_code', '')
                
                # Обновляем файл в ветке
                logger.info(f"📝 Обновление файла {file_path} в ветке {branch_name}...")
                
                # Получаем SHA файла в ветке (или создаем новый)
                file_branch_url = f'https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={branch_name}'
                file_branch_response = requests.get(file_branch_url, headers=headers)
                
                file_sha = None
                if file_branch_response.status_code == 200:
                    file_sha = file_branch_response.json()['sha']
                elif file_branch_response.status_code == 404:
                    # Файл не существует в ветке, создаем новый
                    file_sha = None
                else:
                    raise Exception(f"Не удалось проверить файл в ветке: {file_branch_response.status_code}")
                
                update_file_url = f'https://api.github.com/repos/{owner}/{repo}/contents/{file_path}'
                update_data = {
                    'message': f'Fix: исправление для issue #{issue_number}',
                    'content': base64.b64encode(fixed_code.encode('utf-8')).decode('utf-8'),
                    'branch': branch_name
                }
                
                if file_sha:
                    update_data['sha'] = file_sha
                
                update_response = requests.put(update_file_url, headers=headers, json=update_data)
                
                if update_response.status_code not in [200, 201]:
                    raise Exception(f"Не удалось обновить файл: {update_response.status_code} - {update_response.text}")
                
                logger.info(f"✅ Файл {file_path} обновлен")
                fixed_files.append(file_path)
                
            except Exception as e:
                logger.error(f"❌ Ошибка при обработке файла {file_path}: {str(e)}")
                failed_files.append({'file': file_path, 'error': str(e)})
        
        if not fixed_files:
            logger.error("❌ Не удалось исправить ни одного файла")
            return {
                'success': False,
                'error': 'Не удалось исправить ни одного файла',
                'failed_files': failed_files
            }
        
        # 8. Создаем Pull Request
        logger.info(f"🔀 Создание Pull Request...")
        pr_url = f'https://api.github.com/repos/{owner}/{repo}/pulls'
        
        pr_title = f"Fix: решение для issue #{issue_number}"
        files_list = '\n'.join([f"- `{f}`" for f in fixed_files])
        pr_body = f"""## Описание
Этот PR решает issue #{issue_number}

## Изменения
{files_list}

## Техническое задание
{technical_spec[:2000]}{'...' if len(technical_spec) > 2000 else ''}

## Связанная issue
Closes #{issue_number}
"""
        
        if failed_files:
            pr_body += f"\n## Предупреждения\nНе удалось обработать следующие файлы:\n"
            for failed in failed_files:
                pr_body += f"- `{failed['file']}`: {failed['error']}\n"
        
        pr_data = {
            'title': pr_title,
            'body': pr_body,
            'head': branch_name,
            'base': default_branch
        }
        
        pr_response = requests.post(pr_url, headers=headers, json=pr_data)
        
        if pr_response.status_code not in [201, 422]:
            if pr_response.status_code == 422:
                # PR уже существует, получаем его
                existing_prs_url = f'https://api.github.com/repos/{owner}/{repo}/pulls?head={owner}:{branch_name}&state=open'
                existing_prs_response = requests.get(existing_prs_url, headers=headers)
                if existing_prs_response.status_code == 200:
                    existing_prs = existing_prs_response.json()
                    if existing_prs:
                        pr_data = existing_prs[0]
                        logger.info(f"ℹ️  PR уже существует: {pr_data['html_url']}")
                        return {
                            'success': True,
                            'pr_number': pr_data['number'],
                            'pr_url': pr_data['html_url'],
                            'branch': branch_name,
                            'fixed_files': fixed_files,
                            'failed_files': failed_files
                        }
            raise Exception(f"Не удалось создать PR: {pr_response.status_code} - {pr_response.text}")
        
        pr_data = pr_response.json()
        logger.info(f"✅ Pull Request создан: {pr_data['html_url']}")
        
        return {
            'success': True,
            'pr_number': pr_data['number'],
            'pr_url': pr_data['html_url'],
            'branch': branch_name,
            'fixed_files': fixed_files,
            'failed_files': failed_files
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка при автоматическом исправлении и создании PR: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def create_pull_request(owner, repo, file_path, fixed_code, issue_number, technical_spec, installation_id=None):
    """
    Создает Pull Request с исправленным кодом
    
    Args:
        owner: Владелец репозитория
        repo: Название репозитория
        file_path: Путь к файлу
        fixed_code: Исправленный код
        issue_number: Номер issue
        technical_spec: Техническое задание
        installation_id: ID установки GitHub App (опционально)
        
    Returns:
        dict с информацией о созданном PR
    """
    try:
        # Получаем access token
        if installation_id:
            access_token = get_installation_access_token(installation_id)
            headers = {
                'Authorization': f'token {access_token}',
                'Accept': 'application/vnd.github.v3+json'
            }
        else:
            personal_token = os.getenv('GITHUB_TOKEN')
            if not personal_token:
                raise ValueError("Необходим либо GITHUB_INSTALLATION_ID, либо GITHUB_TOKEN")
            headers = {
                'Authorization': f'token {personal_token}',
                'Accept': 'application/vnd.github.v3+json'
            }
        
        # Получаем информацию о репозитории для определения основной ветки
        repo_url = f'https://api.github.com/repos/{owner}/{repo}'
        repo_response = requests.get(repo_url, headers=headers)
        
        if repo_response.status_code != 200:
            raise Exception(f"Не удалось получить информацию о репозитории: {repo_response.status_code}")
        
        repo_data = repo_response.json()
        default_branch = repo_data.get('default_branch', 'main')
        
        # Создаем имя ветки
        branch_name = f"fix/issue-{issue_number}-{file_path.replace('/', '-').replace('.', '-')}"
        # Ограничиваем длину имени ветки
        if len(branch_name) > 200:
            branch_name = branch_name[:200]
        
        logger.info(f"🌿 Создание ветки {branch_name}...")
        
        # Получаем SHA последнего коммита в основной ветке
        ref_url = f'https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{default_branch}'
        ref_response = requests.get(ref_url, headers=headers)
        
        if ref_response.status_code != 200:
            raise Exception(f"Не удалось получить информацию о ветке {default_branch}: {ref_response.status_code}")
        
        base_sha = ref_response.json()['object']['sha']
        
        # Создаем новую ветку
        create_branch_url = f'https://api.github.com/repos/{owner}/{repo}/git/refs'
        branch_data = {
            'ref': f'refs/heads/{branch_name}',
            'sha': base_sha
        }
        branch_response = requests.post(create_branch_url, headers=headers, json=branch_data)
        
        if branch_response.status_code not in [201, 422]:  # 422 если ветка уже существует
            if branch_response.status_code == 422:
                # Ветка уже существует, получаем её SHA
                existing_branch_url = f'https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{branch_name}'
                existing_response = requests.get(existing_branch_url, headers=headers)
                if existing_response.status_code == 200:
                    base_sha = existing_response.json()['object']['sha']
                    logger.info(f"ℹ️  Ветка {branch_name} уже существует, используем её")
                else:
                    raise Exception(f"Ветка существует, но не удалось получить её SHA: {existing_response.status_code}")
            else:
                raise Exception(f"Не удалось создать ветку: {branch_response.status_code} - {branch_response.text}")
        else:
            logger.info(f"✅ Ветка {branch_name} создана")
        
        # Получаем SHA файла для обновления
        file_url = f'https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={branch_name}'
        file_response = requests.get(file_url, headers=headers)
        
        if file_response.status_code != 200:
            raise Exception(f"Не удалось получить файл для обновления: {file_response.status_code}")
        
        file_data = file_response.json()
        file_sha = file_data['sha']
        
        # Обновляем файл с исправленным кодом
        logger.info(f"📝 Обновление файла {file_path}...")
        update_file_url = f'https://api.github.com/repos/{owner}/{repo}/contents/{file_path}'
        
        update_data = {
            'message': f'Fix: исправление для issue #{issue_number}',
            'content': base64.b64encode(fixed_code.encode('utf-8')).decode('utf-8'),
            'sha': file_sha,
            'branch': branch_name
        }
        
        update_response = requests.put(update_file_url, headers=headers, json=update_data)
        
        if update_response.status_code not in [200, 201]:
            raise Exception(f"Не удалось обновить файл: {update_response.status_code} - {update_response.text}")
        
        logger.info(f"✅ Файл {file_path} обновлен")
        
        # Создаем Pull Request
        logger.info(f"🔀 Создание Pull Request...")
        pr_url = f'https://api.github.com/repos/{owner}/{repo}/pulls'
        
        pr_title = f"Fix: решение для issue #{issue_number}"
        pr_body = f"""## Описание
Этот PR решает issue #{issue_number}

## Изменения
- Исправлен файл: `{file_path}`

## Техническое задание
{technical_spec[:1000]}...

## Связанная issue
Closes #{issue_number}
"""
        
        pr_data = {
            'title': pr_title,
            'body': pr_body,
            'head': branch_name,
            'base': default_branch
        }
        
        pr_response = requests.post(pr_url, headers=headers, json=pr_data)
        
        if pr_response.status_code not in [201, 422]:  # 422 если PR уже существует
            if pr_response.status_code == 422:
                # PR уже существует, получаем его
                existing_prs_url = f'https://api.github.com/repos/{owner}/{repo}/pulls?head={owner}:{branch_name}&state=open'
                existing_prs_response = requests.get(existing_prs_url, headers=headers)
                if existing_prs_response.status_code == 200:
                    existing_prs = existing_prs_response.json()
                    if existing_prs:
                        pr_data = existing_prs[0]
                        logger.info(f"ℹ️  PR уже существует: {pr_data['html_url']}")
                        return {
                            'success': True,
                            'pr_number': pr_data['number'],
                            'pr_url': pr_data['html_url'],
                            'branch': branch_name
                        }
            raise Exception(f"Не удалось создать PR: {pr_response.status_code} - {pr_response.text}")
        
        pr_data = pr_response.json()
        logger.info(f"✅ Pull Request создан: {pr_data['html_url']}")
        
        return {
            'success': True,
            'pr_number': pr_data['number'],
            'pr_url': pr_data['html_url'],
            'branch': branch_name
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании PR: {str(e)}")
        raise

def get_repository_name(owner, repo, installation_id=None):
    """
    Получает название репозитория через GitHub API
    """
    if installation_id:
        access_token = get_installation_access_token(installation_id)
        headers = {
            'Authorization': f'token {access_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
    else:
        # Альтернативный способ: использование личного токена
        personal_token = os.getenv('GITHUB_TOKEN')
        if not personal_token:
            raise ValueError("Необходим либо GITHUB_INSTALLATION_ID, либо GITHUB_TOKEN")
        headers = {
            'Authorization': f'token {personal_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
    
    url = f'https://api.github.com/repos/{owner}/{repo}'
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        repo_data = response.json()
        return {
            'name': repo_data['name'],
            'full_name': repo_data['full_name'],
            'description': repo_data.get('description', ''),
            'url': repo_data['html_url'],
            'language': repo_data.get('language', ''),
            'stars': repo_data['stargazers_count'],
            'forks': repo_data['forks_count']
        }
    else:
        raise Exception(f"Ошибка получения данных репозитория: {response.status_code} - {response.text}")

@app.route('/')
def index():
    """
    Главная страница с информацией о возможностях агента
    """
    return jsonify({
        'name': 'GitHub Issue Analyzer Agent',
        'pid': os.getpid(),
        'file': __file__,
        'description': 'AI агент для анализа GitHub issues и создания технических заданий',
        'version': '1.0.0',
        'capabilities': [
            'Анализ GitHub issues через webhook',
            'Прямой анализ issue по ссылке',
            'Автоматическое создание технических заданий',
            'Интеграция с LangGraph для AI анализа'
        ],
        'endpoints': {
            'GET /': 'Эта страница - информация о возможностях агента',
            'POST /analyze': 'Анализ issue по ссылкам (repo_url и issue_url)',
            'POST /fix-code': 'Исправление кода на основе ТЗ (technical_spec, file_path, repo_url)',
            'POST /test-analyzer': 'Тестирование работы агента-аналитика',
            'GET /repo/<owner>/<repo>': 'Получить информацию о репозитории',
            'GET /health': 'Проверка работоспособности'
        },
        'usage': {
            'analyze_issue': {
                'method': 'POST',
                'url': '/analyze',
                'body': {
                    'repo_url': 'https://github.com/owner/repo',
                    'issue_url': 'https://github.com/owner/repo/issues/1'
                },
                'example': 'curl -X POST http://your-server/analyze -H "Content-Type: application/json" -d \'{"repo_url": "https://github.com/owner/repo", "issue_url": "https://github.com/owner/repo/issues/1"}\''
            }
        }
    })

@app.route('/repo/<owner>/<repo>', methods=['GET'])
def get_repo_info(owner, repo):
    """
    Получает информацию о репозитории
    """
    try:
        # Проверяем, передан ли installation_id явно
        installation_id = request.args.get('installation_id')
        
        # Если не передан, пытаемся найти автоматически
        if not installation_id:
            logger.info(f"🔍 Автоматический поиск installation_id для {owner}/{repo}...")
            installation_id = find_installation_id_for_repo(owner, repo)
        
        # Если не нашли автоматически, используем значение из .env (если есть)
        if not installation_id:
            installation_id = GITHUB_INSTALLATION_ID or None
        
        repo_info = get_repository_name(owner, repo, installation_id)
        return jsonify({
            'success': True,
            'repository': repo_info
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/analyze', methods=['POST', 'GET'])
def analyze_issue():
    """
    Анализирует issue по ссылкам на репозиторий и issue
    Поддерживает как POST (JSON), так и GET (query parameters)
    """
    try:
        # Поддержка GET запросов с query parameters
        if request.method == 'GET':
            repo_url = request.args.get('repo_url')
            issue_url = request.args.get('issue_url')
            
            # Если передан только issue_url, извлекаем repo из него
            if issue_url and not repo_url:
                parsed = parse_github_url(issue_url)
                repo_url = f"https://github.com/{parsed['owner']}/{parsed['repo']}"
        else:
            # POST запрос с JSON
            data = request.get_json() or {}
            repo_url = data.get('repo_url')
            issue_url = data.get('issue_url')
            
            # Если передан только issue_url, извлекаем repo из него
            if issue_url and not repo_url:
                parsed = parse_github_url(issue_url)
                repo_url = f"https://github.com/{parsed['owner']}/{parsed['repo']}"
        
        # Проверяем обязательные параметры
        if not issue_url:
            return jsonify({
                'success': False,
                'error': 'Необходимо указать issue_url (ссылка на issue)'
            }), 400
        
        # Парсим ссылки
        try:
            issue_parsed = parse_github_url(issue_url)
            repo_parsed = parse_github_url(repo_url) if repo_url else issue_parsed
            
            owner = issue_parsed['owner']
            repo = issue_parsed['repo']
            issue_number = issue_parsed['issue_number']
            
            if not issue_number:
                return jsonify({
                    'success': False,
                    'error': 'В ссылке issue_url должен быть указан номер issue'
                }), 400
                
        except ValueError as e:
            return jsonify({
                'success': False,
                'error': f'Ошибка парсинга URL: {str(e)}'
            }), 400
        
        # Автоматически определяем installation_id для репозитория
        # Сначала проверяем, не передан ли он явно (для обратной совместимости)
        installation_id = None
        if request.method == 'GET':
            installation_id = request.args.get('installation_id')
        elif request.is_json:
            installation_id = request.json.get('installation_id')
        
        # Если не передан явно, пытаемся найти автоматически
        if not installation_id:
            logger.info(f"🔍 Автоматический поиск installation_id для {owner}/{repo}...")
            installation_id = find_installation_id_for_repo(owner, repo)
        
        # Если не нашли автоматически, используем значение из .env (если есть)
        if not installation_id:
            installation_id = GITHUB_INSTALLATION_ID or None
        
        logger.info(f"🔍 Получение данных issue #{issue_number} из {owner}/{repo}...")
        issue_data = get_issue_data(owner, repo, issue_number, installation_id)
        
        repo_full_name = f"{owner}/{repo}"
        issue_title = issue_data['title']
        issue_body = issue_data['body'] or ''
        
        # Выводим информацию в логи
        logger.info("=" * 80)
        logger.info(f"📝 АНАЛИЗ ISSUE (прямой запрос)")
        logger.info(f"📦 Репозиторий: {repo}")
        logger.info(f"🔗 Полное имя: {repo_full_name}")
        logger.info(f"#️⃣  Номер issue: #{issue_number}")
        logger.info(f"📌 Название issue: {issue_title}")
        logger.info("=" * 80)
        
        # Анализируем issue и создаем ТЗ через AGNO агента
        logger.info("\n🤖 Анализирую issue и создаю техническое задание...")
        try:
            analysis_result = agno_system.analyze_issue(
                issue_title=issue_title,
                issue_body=issue_body,
                repository_name=repo_full_name
            )
            
            if analysis_result.get('success'):
                technical_spec = analysis_result.get('technical_spec', '')
                
                # Выводим ТЗ в логи
                logger.info("\n" + "=" * 80)
                logger.info("📋 ТЕХНИЧЕСКОЕ ЗАДАНИЕ")
                logger.info("=" * 80)
                logger.info(technical_spec)
                logger.info("=" * 80 + "\n")
                
                # Автоматически исправляем код и создаем PR
                logger.info("🚀 Запускаю автоматическое исправление кода и создание PR...")
                try:
                    pr_result = auto_fix_and_create_pr(
                        owner=owner,
                        repo=repo,
                        issue_number=issue_number,
                        technical_spec=technical_spec,
                        installation_id=installation_id
                    )
                    
                    if pr_result.get('success'):
                        logger.info(f"✅ Автоматическое исправление завершено успешно: {pr_result.get('pr_url')}")
                    else:
                        logger.warning(f"⚠️ Автоматическое исправление не удалось: {pr_result.get('error')}")
                except Exception as e:
                    logger.error(f"❌ Ошибка при автоматическом исправлении: {str(e)}")
                    pr_result = None
            else:
                logger.error(f"⚠️ Ошибка при создании ТЗ: {analysis_result.get('error', 'Неизвестная ошибка')}")
                technical_spec = None
                pr_result = None
                
        except Exception as e:
            logger.error(f"⚠️ Ошибка при создании ТЗ: {str(e)}")
            technical_spec = None
            pr_result = None
        
        response_data = {
            'success': True,
            'repository': {
                'name': repo,
                'full_name': repo_full_name,
                'url': f'https://github.com/{repo_full_name}'
            },
            'issue': {
                'number': issue_number,
                'title': issue_title,
                'body': issue_body,
                'url': issue_data['url'],
                'state': issue_data['state'],
                'created_at': issue_data['created_at'],
                'author': issue_data['user']
            },
            'technical_spec': technical_spec,
            'message': f'Issue #{issue_number} "{issue_title}" успешно проанализирована'
        }
        
        if pr_result and pr_result.get('success'):
            response_data['pull_request'] = {
                'number': pr_result.get('pr_number'),
                'url': pr_result.get('pr_url'),
                'branch': pr_result.get('branch'),
                'fixed_files': pr_result.get('fixed_files', [])
            }
            response_data['message'] += f'. Pull Request создан: {pr_result.get("pr_url")}'
        elif pr_result:
            response_data['pr_error'] = pr_result.get('error')
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при анализе issue: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Обработчик webhook от GitHub
    """
    try:
        # Получаем сырое тело запроса для проверки подписи
        payload_body = request.get_data()
        
        # Проверяем подпись webhook
        signature_header = request.headers.get('X-Hub-Signature-256')
        if not verify_webhook_signature(payload_body, signature_header):
            logger.error("❌ Ошибка: Неверная подпись webhook")
            return jsonify({
                'error': 'Неверная подпись webhook'
            }), 401
        
        # Парсим JSON payload
        payload = request.json
        event_type = request.headers.get('X-GitHub-Event')
        
        logger.info(f"📥 Получено событие: {event_type}")
        
        # Обработка установки GitHub App
        if event_type == 'installation' and payload.get('action') == 'created':
            installation_id = payload['installation']['id']
            logger.info(f"✅ GitHub App установлен! Installation ID: {installation_id}")
            return jsonify({
                'message': f'GitHub App установлен! Installation ID: {installation_id}',
                'installation_id': installation_id
            })
        
        # Обработка создания issue
        if event_type == 'issues' and payload.get('action') == 'opened':
            issue = payload.get('issue', {})
            repository = payload.get('repository', {})
            
            repo_name = repository.get('name', 'Неизвестный репозиторий')
            repo_full_name = repository.get('full_name', 'Неизвестный репозиторий')
            issue_title = issue.get('title', 'Без названия')
            issue_body = issue.get('body', '')
            issue_number = issue.get('number', '?')
            
            # Выводим в логи имя репозитория и название issue
            logger.info("=" * 60)
            logger.info(f"📝 СОЗДАНА НОВАЯ ISSUE")
            logger.info(f"📦 Репозиторий: {repo_name}")
            logger.info(f"🔗 Полное имя: {repo_full_name}")
            logger.info(f"#️⃣  Номер issue: #{issue_number}")
            logger.info(f"📌 Название issue: {issue_title}")
            logger.info("=" * 60)
            
            # Анализируем issue и создаем ТЗ через AGNO агента
            logger.info("\n🤖 Анализирую issue и создаю техническое задание...")
            try:
                analysis_result = agno_system.analyze_issue(
                    issue_title=issue_title,
                    issue_body=issue_body,
                    repository_name=repo_full_name
                )
                
                if analysis_result.get('success'):
                    technical_spec = analysis_result.get('technical_spec', '')
                    
                    # Выводим ТЗ в логи
                    logger.info("\n" + "=" * 80)
                    logger.info("📋 ТЕХНИЧЕСКОЕ ЗАДАНИЕ")
                    logger.info("=" * 80)
                    logger.info(technical_spec)
                    logger.info("=" * 80 + "\n")
                    
                    # Автоматически исправляем код и создаем PR
                    logger.info("🚀 Запускаю автоматическое исправление кода и создание PR...")
                    try:
                        # Извлекаем owner и repo из repo_full_name
                        repo_parts = repo_full_name.split('/')
                        if len(repo_parts) == 2:
                            repo_owner = repo_parts[0]
                            repo_repo = repo_parts[1]
                        else:
                            raise ValueError(f"Неверный формат repo_full_name: {repo_full_name}")
                        
                        # Получаем installation_id из payload
                        installation_id = payload.get('installation', {}).get('id')
                        if not installation_id:
                            installation_id = find_installation_id_for_repo(repo_owner, repo_repo)
                        if not installation_id:
                            installation_id = GITHUB_INSTALLATION_ID or None
                        
                        pr_result = auto_fix_and_create_pr(
                            owner=repo_owner,
                            repo=repo_repo,
                            issue_number=issue_number,
                            technical_spec=technical_spec,
                            installation_id=installation_id
                        )
                        
                        if pr_result.get('success'):
                            logger.info(f"✅ Автоматическое исправление завершено успешно: {pr_result.get('pr_url')}")
                        else:
                            logger.warning(f"⚠️ Автоматическое исправление не удалось: {pr_result.get('error')}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка при автоматическом исправлении: {str(e)}")
                        pr_result = None
                else:
                    logger.error(f"⚠️ Ошибка при создании ТЗ: {analysis_result.get('error', 'Неизвестная ошибка')}")
                    technical_spec = None
                    pr_result = None
                    
            except Exception as e:
                logger.error(f"⚠️ Ошибка при создании ТЗ: {str(e)}")
                technical_spec = None
                pr_result = None
            
            response_data = {
                'success': True,
                'event': 'issue_opened',
                'repository': {
                    'name': repo_name,
                    'full_name': repo_full_name
                },
                'issue': {
                    'number': issue_number,
                    'title': issue_title,
                    'url': issue.get('html_url', ''),
                    'body': issue_body
                },
                'technical_spec': technical_spec if technical_spec else None,
                'message': f'Issue #{issue_number} "{issue_title}" создана в репозитории {repo_full_name}'
            }
            
            if pr_result and pr_result.get('success'):
                response_data['pull_request'] = {
                    'number': pr_result.get('pr_number'),
                    'url': pr_result.get('pr_url'),
                    'branch': pr_result.get('branch'),
                    'fixed_files': pr_result.get('fixed_files', [])
                }
                response_data['message'] += f'. Pull Request создан: {pr_result.get("pr_url")}'
            elif pr_result:
                response_data['pr_error'] = pr_result.get('error')
            
            return jsonify(response_data)
        
        # Обработка других событий репозитория
        if 'repository' in payload:
            repo = payload['repository']
            repo_name = repo.get('name')
            repo_full_name = repo.get('full_name')
            
            logger.info(f"📦 Событие {event_type} для репозитория: {repo_full_name}")
            
            return jsonify({
                'event': event_type,
                'repository_name': repo_name,
                'repository_full_name': repo_full_name,
                'message': f'Получено событие {event_type} для репозитория {repo_full_name}'
            })
        
        logger.info(f"ℹ️  Необработанное событие: {event_type}")
        return jsonify({
            'event': event_type,
            'message': 'Webhook получен'
        })
    except Exception as e:
        logger.error(f"❌ Ошибка обработки webhook: {str(e)}")
        return jsonify({
            'error': str(e)
        }), 500

@app.route('/fix-code', methods=['POST'])
def fix_code():
    """
    Исправляет код на основе технического задания через агента-разработчика
    """
    try:
        data = request.get_json() or {}
        
        technical_spec = data.get('technical_spec')
        file_path = data.get('file_path')
        repo_url = data.get('repo_url')
        issue_url = data.get('issue_url')
        issue_number = data.get('issue_number')
        owner = data.get('owner')
        repo = data.get('repo')
        
        # Парсим repo_url если передан
        if repo_url and not owner:
            try:
                parsed = parse_github_url(repo_url)
                owner = parsed['owner']
                repo = parsed['repo']
            except ValueError as e:
                return jsonify({
                    'success': False,
                    'error': f'Ошибка парсинга repo_url: {str(e)}'
                }), 400
        
        # Парсим issue_url для получения issue_number
        if issue_url and not issue_number:
            try:
                parsed = parse_github_url(issue_url)
                issue_number = parsed.get('issue_number')
                if not owner:
                    owner = parsed['owner']
                    repo = parsed['repo']
            except ValueError:
                pass  # Игнорируем ошибку, если issue_number не найден
        
        if not all([technical_spec, file_path, owner, repo]):
            return jsonify({
                'success': False,
                'error': 'Необходимы параметры: technical_spec, file_path, owner, repo (или repo_url)'
            }), 400
        
        if not issue_number:
            return jsonify({
                'success': False,
                'error': 'Необходим issue_number или issue_url для создания PR'
            }), 400
        
        # Автоматически определяем installation_id
        installation_id = find_installation_id_for_repo(owner, repo)
        if not installation_id:
            installation_id = GITHUB_INSTALLATION_ID or None
        
        # Получаем текущий код файла через GitHub API
        logger.info(f"📥 Получение кода файла {file_path} из {owner}/{repo}...")
        try:
            if installation_id:
                access_token = get_installation_access_token(installation_id)
                headers = {
                    'Authorization': f'token {access_token}',
                    'Accept': 'application/vnd.github.v3+json'
                }
            else:
                personal_token = os.getenv('GITHUB_TOKEN')
                if not personal_token:
                    raise ValueError("Необходим либо GITHUB_INSTALLATION_ID, либо GITHUB_TOKEN")
                headers = {
                    'Authorization': f'token {personal_token}',
                    'Accept': 'application/vnd.github.v3+json'
                }
            
            # Получаем содержимое файла
            file_url = f'https://api.github.com/repos/{owner}/{repo}/contents/{file_path}'
            file_response = requests.get(file_url, headers=headers)
            
            if file_response.status_code != 200:
                return jsonify({
                    'success': False,
                    'error': f'Не удалось получить файл: {file_response.status_code} - {file_response.text}'
                }), 400
            
            file_data = file_response.json()
            current_code = base64.b64decode(file_data['content']).decode('utf-8')
            
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Ошибка получения файла: {str(e)}'
            }), 500
        
        # Исправляем код через агента-разработчика
        logger.info(f"🔧 Исправление кода файла {file_path}...")
        fix_result = agno_system.fix_code(
            technical_spec=technical_spec,
            file_path=file_path,
            current_code=current_code,
            repository_name=f"{owner}/{repo}"
        )
        
        if fix_result.get('success'):
            fixed_code = fix_result.get('fixed_code', '')
            
            logger.info("=" * 80)
            logger.info(f"✅ КОД ИСПРАВЛЕН для файла {file_path}")
            logger.info("=" * 80)
            logger.info(fixed_code)
            logger.info("=" * 80)
            
            # Создаем Pull Request
            pr_result = None
            try:
                logger.info(f"🔀 Создание Pull Request для issue #{issue_number}...")
                pr_result = create_pull_request(
                    owner=owner,
                    repo=repo,
                    file_path=file_path,
                    fixed_code=fixed_code,
                    issue_number=issue_number,
                    technical_spec=technical_spec,
                    installation_id=installation_id
                )
                logger.info(f"✅ Pull Request успешно создан: {pr_result.get('pr_url', 'N/A')}")
            except Exception as e:
                logger.error(f"⚠️ Ошибка при создании PR: {str(e)}")
                # Не прерываем выполнение, возвращаем результат исправления кода
            
            response_data = {
                'success': True,
                'file_path': file_path,
                'fixed_code': fixed_code,
                'repository': f"{owner}/{repo}",
                'message': f'Код файла {file_path} успешно исправлен'
            }
            
            if pr_result and pr_result.get('success'):
                response_data['pull_request'] = {
                    'number': pr_result.get('pr_number'),
                    'url': pr_result.get('pr_url'),
                    'branch': pr_result.get('branch')
                }
                response_data['message'] = f'Код исправлен и Pull Request создан: {pr_result.get("pr_url")}'
            
            return jsonify(response_data)
        else:
            return jsonify({
                'success': False,
                'error': fix_result.get('error', 'Неизвестная ошибка')
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Ошибка при исправлении кода: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/test-analyzer', methods=['POST', 'GET'])
def test_analyzer():
    """
    Тестовый endpoint для проверки работы агента-аналитика
    """
    try:
        # Тестовые данные
        if request.method == 'POST':
            data = request.get_json() or {}
            test_title = data.get('title', 'Тестовая issue')
            test_body = data.get('body', 'Это тестовое описание issue для проверки работы модели анализа.')
            test_repo = data.get('repository', 'test/repo')
        else:
            test_title = 'Тестовая issue'
            test_body = 'Это тестовое описание issue для проверки работы модели анализа.'
            test_repo = 'test/repo'
        
        logger.info("🧪 Тестирование агента-аналитика...")
        
        # Проверяем настройки
        api_key = os.getenv('OPENAI_API_KEY')
        base_url = os.getenv('OPENAI_BASE_URL', '')
        use_deepseek = os.getenv('USE_DEEPSEEK', '').lower() in ('true', '1', 'yes')
        model = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
        
        config_info = {
            'api_key_set': bool(api_key),
            'api_key_length': len(api_key) if api_key else 0,
            'base_url': base_url or 'default (OpenAI)',
            'use_deepseek': use_deepseek,
            'model': model
        }
        
        if not api_key:
            return jsonify({
                'success': False,
                'error': 'OPENAI_API_KEY не установлен',
                'config': config_info
            }), 400
        
        # Тестируем анализ
        result = agno_system.analyze_issue(
            issue_title=test_title,
            issue_body=test_body,
            repository_name=test_repo
        )
        
        if result.get('success'):
            technical_spec = result.get('technical_spec', '')
            return jsonify({
                'success': True,
                'config': config_info,
                'test_input': {
                    'title': test_title,
                    'body': test_body,
                    'repository': test_repo
                },
                'result': {
                    'technical_spec': technical_spec,
                    'spec_length': len(technical_spec)
                },
                'message': 'Агент-аналитик работает корректно'
            })
        else:
            return jsonify({
                'success': False,
                'config': config_info,
                'error': result.get('error', 'Неизвестная ошибка')
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Ошибка при тестировании: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health():
    """
    Проверка работоспособности
    """
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    logger.info(f"🚀 Запуск GitHub Issue Analyzer Agent на порту {port}")
    logger.info(f"📡 Сервер будет доступен на http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
