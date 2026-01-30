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
import subprocess
import tempfile
import shutil
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv
from agents import AGNOAgentSystem
from github import (
    get_github_app_private_key,
    get_github_app_token,
    get_installation_access_token,
    find_installation_id_for_repo,
    verify_webhook_signature,
    parse_github_url,
    get_issue_data,
    get_repository_name,
    get_repository_structure,
    create_pr_from_branch,
    create_pr_comment
)
from github.config import GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_INSTALLATION_ID, WEBHOOK_SECRET
from ci.checker import check_ci_results_match

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

# Конфигурация GitHub App импортируется из github.config

# Удаляем старые функции, которые теперь в модулях github
# def get_github_app_private_key(): - теперь в github.auth
# def get_github_app_token(): - теперь в github.auth
# def get_installation_access_token(): - теперь в github.auth
# def find_installation_id_for_repo(): - теперь в github.auth
# def verify_webhook_signature(): - теперь в github.webhook
# def parse_github_url(): - теперь в github.webhook
# def get_issue_data(): - теперь в github.api
# def get_repository_name(): - теперь в github.api
# def get_repository_structure(): - теперь в github.api
# def create_pr_comment(): - теперь в github.branches
# def create_pr_from_branch(): - теперь в github.branches

# Все функции GitHub API теперь импортируются из модулей github
# (см. импорты в начале файла)

# Удалены дублирующие функции:
# - get_github_app_private_key, get_github_app_token, get_installation_access_token, 
#   find_installation_id_for_repo -> теперь в github.auth
# - verify_webhook_signature, parse_github_url -> теперь в github.webhook
# - get_issue_data, get_repository_name, get_repository_structure -> теперь в github.api
# - create_pr_comment, create_pr_from_branch -> теперь в github.branches

def _placeholder_removed():
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

# get_issue_data теперь импортируется из github.api

# check_ci_results_match теперь импортируется из ci.checker

def auto_fix_and_create_pr_with_review(owner, repo, issue_number, issue_title, issue_body, 
                                       technical_spec, ci_commands, ci_before, installation_id=None, max_iterations=10):
    """
    Автоматически исправляет код, проверяет через Reviewer и создает PR с циклом итераций
    
    Args:
        owner: Владелец репозитория
        repo: Название репозитория
        issue_number: Номер issue
        issue_title: Название issue
        issue_body: Описание issue
        technical_spec: Техническое задание
        ci_commands: Команды для CI
        ci_before: Результаты CI до изменений
        installation_id: ID установки GitHub App
        max_iterations: Максимальное количество итераций
        
    Returns:
        dict с информацией о созданном PR или ошибке
    """
    repo_full_name = f"{owner}/{repo}"
    current_spec = technical_spec
    iteration = 0
    pr_number = None  # Номер PR, создается на первой итерации
    
    while iteration < max_iterations:
        iteration += 1
        logger.info(f"\n{'='*80}")
        logger.info(f"🔄 ИТЕРАЦИЯ {iteration}/{max_iterations}")
        logger.info(f"{'='*80}\n")
        
        try:
            # 1. Определяем файлы для изменения
            logger.info("🔍 Определяю файлы для изменения на основе ТЗ...")
            files_result = agno_system.determine_files_to_change(current_spec, repo_full_name)
            
            if not files_result.get('success'):
                logger.error(f"❌ Ошибка при определении файлов: {files_result.get('error')}")
                return {
                    'success': False,
                    'error': f"Не удалось определить файлы: {files_result.get('error')}",
                    'iteration': iteration
                }
            
            files_to_change = files_result.get('files', [])
            
            if not files_to_change:
                logger.warning("⚠️ Не удалось определить файлы для изменения.")
                if iteration == 1:
                    return {
                        'success': False,
                        'error': 'Не удалось определить файлы для изменения из технического задания',
                        'technical_spec': current_spec
                    }
                else:
                    # Если это не первая итерация, возможно нужно уточнить ТЗ
                    logger.info("🔄 Пытаюсь уточнить техническое задание...")
                    # Создаем новое ТЗ на основе предыдущих проблем
                    continue
            
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
            
            # 4. Создаем имя ветки (одна ветка для всех итераций)
            branch_name = f"fix/issue-{issue_number}"
            if len(branch_name) > 200:
                branch_name = branch_name[:200]
            
            logger.info(f"🌿 Создание/обновление ветки {branch_name}...")
            
            # 4. Получаем SHA последнего коммита в ветке (или основной ветке, если ветка не существует)
            ref_url = f'https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{branch_name}'
            ref_response = requests.get(ref_url, headers=headers)
            
            if ref_response.status_code == 200:
                base_sha = ref_response.json()['object']['sha']
                logger.info(f"ℹ️  Ветка {branch_name} существует, используем её")
            else:
                # Ветка не существует, создаем её от основной ветки
                default_ref_url = f'https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{default_branch}'
                default_ref_response = requests.get(default_ref_url, headers=headers)
                
                if default_ref_response.status_code != 200:
                    raise Exception(f"Не удалось получить информацию о ветке {default_branch}: {default_ref_response.status_code}")
                
                base_sha = default_ref_response.json()['object']['sha']
                
                # Создаем ветку
                create_branch_url = f'https://api.github.com/repos/{owner}/{repo}/git/refs'
                branch_data = {
                    'ref': f'refs/heads/{branch_name}',
                    'sha': base_sha
                }
                branch_response = requests.post(create_branch_url, headers=headers, json=branch_data)
                
                if branch_response.status_code == 201:
                    logger.info(f"✅ Ветка {branch_name} создана")
                elif branch_response.status_code == 422:
                    logger.info(f"ℹ️  Ветка {branch_name} уже существует")
                else:
                    raise Exception(f"Не удалось создать ветку: {branch_response.status_code} - {branch_response.text}")
            
            # 7. Для каждого файла получаем код, исправляем и обновляем
            fixed_files = []
            failed_files = []
            
            for file_path in files_to_change:
                try:
                    logger.info(f"📥 Получение кода файла {file_path}...")
                    
                    # Получаем содержимое файла из основной ветки
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
                        technical_spec=current_spec,
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
                        'message': f'Fix: исправление для issue #{issue_number} (итерация {iteration})',
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
                if iteration < max_iterations:
                    logger.info("🔄 Продолжаю с следующей итерацией...")
                    continue
                return {
                    'success': False,
                    'error': 'Не удалось исправить ни одного файла',
                    'failed_files': failed_files,
                    'iteration': iteration
                }
            
            # 8. Создаем PR после первого коммита (только на первой итерации, если PR еще не создан)
            if iteration == 1 and pr_number is None:
                logger.info(f"🔀 Создание Pull Request после первого коммита...")
                try:
                    pr_result = create_pr_from_branch(
                        owner=owner,
                        repo=repo,
                        branch_name=branch_name,
                        default_branch=default_branch,
                        issue_number=issue_number,
                        technical_spec=current_spec,
                        fixed_files=fixed_files,
                        failed_files=failed_files,
                        installation_id=installation_id
                    )
                    
                    if pr_result.get('success'):
                        pr_number = pr_result.get('pr_number')
                        logger.info(f"✅ PR создан: #{pr_number} - {pr_result.get('pr_url')}")
                    else:
                        logger.warning(f"⚠️ Не удалось создать PR: {pr_result.get('error')}")
                        # Продолжаем работу даже если PR не создан
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка при создании PR: {str(e)}")
                    # Продолжаем работу даже если PR не создан
            
            # 9. Запускаем CI после изменений
            logger.info(f"🧪 Запуск CI после изменений на ветке {branch_name}...")
            ci_after = run_ci_commands(owner, repo, branch_name, ci_commands, installation_id)
            
            if not ci_after.get('success'):
                logger.warning(f"⚠️ Не удалось запустить CI: {ci_after.get('error')}")
                ci_after = {'summary': {'build_passed': None, 'test_passed': None, 'quality_passed': None}}
            
            # 10. Проверяем совпадение результатов CI программно
            logger.info(f"🔍 Проверка совпадения результатов CI...")
            ci_match_result = check_ci_results_match(ci_before, ci_after)
            
            if not ci_match_result.get('match'):
                logger.error(f"❌ Результаты CI не совпадают: {ci_match_result.get('reason')}")
                # Автоматически отклоняем, даже не отправляя в Reviewer
                review_result = {
                    'success': True,
                    'approved': False,
                    'reason': f"Результаты CI не совпадают: {ci_match_result.get('reason')}",
                    'issues': ci_match_result.get('issues', []),
                    'recommendations': ci_match_result.get('recommendations', [])
                }
            else:
                logger.info(f"✅ Результаты CI совпадают или улучшились")
                # 11. Проверяем через Reviewer
                logger.info(f"👀 Проверка изменений через Reviewer...")
                review_result = agno_system.review_changes(
                    issue_title=issue_title,
                    issue_body=issue_body,
                    technical_spec=current_spec,
                    changed_files=fixed_files,
                    ci_before=ci_before,
                    ci_after=ci_after,
                    repository_name=repo_full_name
                )
                
                # Дополнительная проверка: даже если Reviewer одобрил, проверяем CI еще раз
                if review_result.get('success') and review_result.get('approved'):
                    if not ci_match_result.get('match'):
                        logger.warning(f"⚠️ Reviewer одобрил, но результаты CI не совпадают. Отклоняю автоматически.")
                        review_result['approved'] = False
                        review_result['reason'] = f"Автоматическое отклонение: {ci_match_result.get('reason')}"
            
            # 12. Добавляем комментарий от Reviewer в PR
            if pr_number:
                logger.info(f"💬 Добавление комментария Reviewer в PR #{pr_number}...")
                
                # Формируем комментарий от Reviewer
                review_comment = f"""## 👀 Review - Итерация {iteration}

**Вердикт:** {'✅ Одобрено' if review_result.get('approved') else '❌ Отклонено'}

**Причина:** {review_result.get('reason', 'Не указана')}

"""
                
                if review_result.get('issues'):
                    review_comment += f"**Проблемы:**\n"
                    for issue in review_result.get('issues', []):
                        review_comment += f"- {issue}\n"
                    review_comment += "\n"
                
                if review_result.get('recommendations'):
                    review_comment += f"**Рекомендации:**\n"
                    for rec in review_result.get('recommendations', []):
                        review_comment += f"- {rec}\n"
                    review_comment += "\n"
                
                # Добавляем информацию о CI
                review_comment += f"**Результаты CI:**\n"
                review_comment += f"- Проверка синтаксиса: {'✅' if ci_after.get('summary', {}).get('build_passed') else '❌'}\n"
                review_comment += f"- Тесты: {'✅' if ci_after.get('summary', {}).get('test_passed') else '❌'}\n"
                
                create_pr_comment(owner, repo, pr_number, review_comment, installation_id)
            
            if review_result.get('success') and review_result.get('approved'):
                logger.info(f"✅ Reviewer одобрил изменения!")
                
                # Добавляем комментарий о качестве кода, если есть результаты
                if pr_number and ci_after.get('results', {}).get('quality'):
                    quality_result = ci_after.get('results', {}).get('quality', {})
                    quality_passed = quality_result.get('success')
                    
                    quality_comment = f"""## 📊 Анализ качества кода

**Статус:** {'✅ Проверка пройдена' if quality_passed else '⚠️ Есть замечания'}

"""
                    if quality_result.get('output'):
                        quality_comment += f"**Результаты проверки:**\n```\n{quality_result.get('output', '')[:2000]}\n```\n"
                    
                    if quality_result.get('error'):
                        quality_comment += f"**Предупреждения:**\n```\n{quality_result.get('error', '')[:1000]}\n```\n"
                    
                    quality_comment += "\n*Примечание: Качество кода не влияет на решение Reviewer, только синтаксис и тесты.*"
                    
                    create_pr_comment(owner, repo, pr_number, quality_comment, installation_id)
                
                return {
                    'success': True,
                    'pr_number': pr_number,
                    'pr_url': f'https://github.com/{owner}/{repo}/pull/{pr_number}' if pr_number else None,
                    'branch': branch_name,
                    'fixed_files': fixed_files,
                    'failed_files': failed_files,
                    'iteration': iteration,
                    'review': review_result
                }
            else:
                logger.warning(f"❌ Reviewer не одобрил изменения: {review_result.get('reason', 'Не указана причина')}")
                
                if iteration >= max_iterations:
                    logger.error(f"❌ Достигнуто максимальное количество итераций ({max_iterations})")
                    return {
                        'success': False,
                        'error': f'Не удалось получить одобрение Reviewer после {max_iterations} итераций',
                        'review': review_result,
                        'iteration': iteration,
                        'pr_number': pr_number
                    }
                
                # Создаем новое ТЗ на основе проблем от Reviewer
                logger.info(f"📝 Создание уточненного технического задания на основе замечаний Reviewer...")
                issues_text = "\n".join([f"- {issue}" for issue in review_result.get('issues', [])])
                recommendations_text = "\n".join([f"- {rec}" for rec in review_result.get('recommendations', [])])
                
                refinement_prompt = f"""
ПРЕДЫДУЩЕЕ ТЕХНИЧЕСКОЕ ЗАДАНИЕ:
{current_spec}

ИСХОДНАЯ ЗАДАЧА:
Название: {issue_title}
Описание: {issue_body}

ПРОБЛЕМЫ, ВЫЯВЛЕННЫЕ REVIEWER:
{issues_text if issues_text else 'Не указаны'}

РЕКОМЕНДАЦИИ REVIEWER:
{recommendations_text if recommendations_text else 'Не указаны'}

РЕЗУЛЬТАТЫ CI:
Проверка синтаксиса до: {'✅' if ci_before.get('summary', {}).get('build_passed') else '❌'}
Проверка синтаксиса после: {'✅' if ci_after.get('summary', {}).get('build_passed') else '❌'}
Тесты до: {'✅' if ci_before.get('summary', {}).get('test_passed') else '❌'}
Тесты после: {'✅' if ci_after.get('summary', {}).get('test_passed') else '❌'}

Создай уточненное техническое задание, которое учитывает замечания Reviewer и исправляет выявленные проблемы.
"""
                
                refinement_result = agno_system.analyzer.client.chat.completions.create(
                    model=agno_system.analyzer.model,
                    messages=[
                        {"role": "system", "content": agno_system.analyzer.instructions},
                        {"role": "user", "content": refinement_prompt}
                    ],
                    temperature=0
                )
                
                current_spec = refinement_result.choices[0].message.content
                logger.info(f"📋 Создано уточненное ТЗ (длина: {len(current_spec)} символов)")
                logger.info(f"🔄 Переход к следующей итерации...")
                continue
                
        except Exception as e:
            logger.error(f"❌ Ошибка на итерации {iteration}: {str(e)}")
            if iteration >= max_iterations:
                return {
                    'success': False,
                    'error': str(e),
                    'iteration': iteration
                }
            continue
    
    return {
        'success': False,
        'error': f'Достигнуто максимальное количество итераций ({max_iterations})',
        'iteration': max_iterations
    }

# create_pr_comment и create_pr_from_branch теперь импортируются из github.branches


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
        
        if branch_response.status_code == 201:
            logger.info(f"✅ Ветка {branch_name} создана")
        elif branch_response.status_code == 422:
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
        
        if branch_response.status_code == 201:
            logger.info(f"✅ Ветка {branch_name} создана")
        elif branch_response.status_code == 422:
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

# get_repository_structure теперь импортируется из github.api

def check_tests_exist(files, key_files):
    """
    Проверяет наличие тестов в репозитории
    
    Returns:
        bool: True если тесты найдены, False если нет
    """
    # Паттерны для тестовых файлов и директорий
    test_patterns = [
        'test', 'tests', 'spec', 'specs', '__test__', '__tests__',
        'test_', '_test', '.test.', '.spec.'
    ]
    
    # Проверяем наличие тестовых директорий
    test_dirs = [f for f in files if f['type'] == 'directory' and 
                 any(pattern in f['path'].lower() for pattern in test_patterns)]
    
    # Проверяем наличие тестовых файлов
    test_files = [f for f in files if f['type'] == 'file' and 
                  any(pattern in f['path'].lower() for pattern in test_patterns)]
    
    # Проверяем package.json для npm тестов
    if 'package.json' in key_files:
        import json
        try:
            package_content = key_files['package.json']
            if 'test' in package_content.lower() or '"test"' in package_content:
                return True
        except:
            pass
    
    # Проверяем наличие pytest.ini, tox.ini, jest.config и т.д.
    test_config_files = ['pytest.ini', 'tox.ini', 'jest.config.js', 'jest.config.ts', 
                        'vitest.config.js', 'vitest.config.ts', '.mocharc.js', '.mocharc.json']
    has_test_config = any(any(f['path'].endswith(config) for f in files if f['type'] == 'file') 
                          for config in test_config_files)
    
    return len(test_dirs) > 0 or len(test_files) > 0 or has_test_config

def determine_ci_commands(owner, repo, installation_id=None):
    """
    Определяет команды для проверки синтаксиса, тестов и проверки качества кода на основе структуры репозитория
    Анализирует конкретный проект и определяет подходящие команды
    ВАЖНО: Не собирает проект, только проверяет синтаксические ошибки
    
    Returns:
        dict с командами для CI (build_command используется для проверки синтаксиса)
    """
    try:
        logger.info(f"🔍 Анализирую репозиторий {owner}/{repo} для определения CI команд...")
        
        # Получаем структуру репозитория с большей глубиной для лучшего анализа
        repo_structure = get_repository_structure(owner, repo, installation_id=installation_id, max_depth=3)
        
        if not repo_structure.get('success'):
            return {
                'success': False,
                'error': repo_structure.get('error', 'Не удалось получить структуру репозитория')
            }
        
        key_files = repo_structure.get('key_files', {})
        files = repo_structure.get('files', [])
        language = repo_structure.get('language', '')
        default_branch = repo_structure.get('default_branch', 'main')
        
        # Проверяем наличие тестов
        has_tests = check_tests_exist(files, key_files)
        logger.info(f"📋 Наличие тестов: {'✅ Найдены' if has_tests else '❌ Не найдены'}")
        
        # Формируем детальную информацию о структуре
        all_files = [f['path'] for f in files if f['type'] == 'file']
        directories = [f['path'] for f in files if f['type'] == 'directory']
        
        # Получаем больше информации о ключевых файлах
        files_info = "\n".join([f"- {f['path']} ({f['type']})" for f in files[:100]])  # Первые 100 файлов
        key_files_info = "\n".join([f"### {name}\n{content[:2000]}" for name, content in key_files.items()])
        
        # Детальная информация о структуре
        structure_summary = f"""
Директории: {', '.join(directories[:20])}
Всего файлов: {len(all_files)}
Язык проекта: {language}
Основная ветка: {default_branch}
"""
        
        prompt = f"""
РЕПОЗИТОРИЙ: {owner}/{repo}
ЯЗЫК ПРОЕКТА: {language}
ОСНОВНАЯ ВЕТКА: {default_branch}

СТРУКТУРА РЕПОЗИТОРИЯ:
{structure_summary}

СПИСОК ФАЙЛОВ И ДИРЕКТОРИЙ:
{files_info}

СОДЕРЖИМОЕ КЛЮЧЕВЫХ ФАЙЛОВ:
{key_files_info}

НАЛИЧИЕ ТЕСТОВ: {'Да, тесты найдены' if has_tests else 'Нет, тесты не найдены'}

ВАЖНО:
1. Проанализируй КОНКРЕТНЫЙ проект и определи команды, специфичные для этого проекта
2. Если тестов НЕТ - установи test_command в null (НЕ включай команду запуска тестов)
3. Если тесты ЕСТЬ - определи правильную команду для их запуска на основе структуры проекта
4. Команды должны быть специфичны для этого конкретного проекта, а не общие
5. НЕ собирай проект! Только проверяй синтаксис кода

Определи команды для:
1. Проверки синтаксиса кода (syntax_check_command) - ОБЯЗАТЕЛЬНО, команда для проверки синтаксических ошибок БЕЗ сборки проекта:
   - Python: python -m py_compile или python -m ast для проверки синтаксиса
   - JavaScript/Node.js: node --check для проверки синтаксиса JS файлов
   - TypeScript: tsc --noEmit для проверки типов и синтаксиса без компиляции
   - Java: javac -Xlint для проверки синтаксиса без компиляции
   - Rust: cargo check (уже проверяет без сборки)
   - Go: go build -o /dev/null ./... или go vet для проверки синтаксиса
   - Другие языки: аналогичные команды только для проверки синтаксиса
2. Запуска тестов (test_command) - ТОЛЬКО если тесты найдены, иначе null
3. Проверки качества кода (quality_command) - опционально, может быть null
4. Рабочая директория (working_directory) - если команды нужно запускать из поддиректории

Верни JSON объект в формате:
{{
    "syntax_check_command": "команда для проверки синтаксиса или null",
    "test_command": "команда для запуска тестов или null (только если тесты есть!)",
    "quality_command": "команда для проверки качества кода или null",
    "working_directory": "директория для выполнения команд или ."
}}

ВАЖНО: НЕ используй команды сборки (build, compile, install). Только проверка синтаксиса!

Отвечай ТОЛЬКО JSON объектом, без дополнительных комментариев.
"""
        
        # Используем агента-аналитика для определения команд
        response = agno_system.analyzer.client.chat.completions.create(
            model=agno_system.analyzer.model,
            messages=[
                {"role": "system", "content": "Ты опытный DevOps инженер, который анализирует структуру конкретного репозитория и определяет команды ТОЛЬКО для проверки синтаксиса кода (БЕЗ сборки проекта), тестов и проверки качества кода. НЕ используй команды сборки (build, compile). Только проверка синтаксиса. Если тестов нет - не включай test_command. Отвечай только JSON объектом."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        
        commands_text = response.choices[0].message.content.strip()
        
        # Извлекаем JSON
        if "```json" in commands_text:
            commands_text = commands_text.split("```json")[1].split("```")[0].strip()
        elif "```" in commands_text:
            commands_text = commands_text.split("```")[1].split("```")[0].strip()
        
        import json
        try:
            commands = json.loads(commands_text)
            
            # Переименовываем syntax_check_command в build_command для обратной совместимости
            if 'syntax_check_command' in commands and commands['syntax_check_command']:
                commands['build_command'] = commands.pop('syntax_check_command')
            elif 'build_command' not in commands or not commands.get('build_command'):
                # Если нет ни того, ни другого, пытаемся определить эвристически
                logger.warning(f"⚠️ Не найдена команда проверки синтаксиса, использую эвристику")
                heuristic_result = determine_ci_commands_heuristic(key_files, language, files, has_tests)
                if heuristic_result.get('success'):
                    commands = heuristic_result.get('commands', commands)
            
            # Дополнительная проверка: если тестов нет, принудительно убираем test_command
            if not has_tests:
                if commands.get('test_command'):
                    logger.info(f"⚠️ Тесты не найдены, но AI предложил test_command. Убираю его.")
                commands['test_command'] = None
            
            # Валидация: если test_command есть, но тестов нет - это ошибка
            if commands.get('test_command') and not has_tests:
                commands['test_command'] = None
                logger.warning(f"⚠️ Исправлено: test_command убран, так как тесты не найдены")
            
            logger.info(f"✅ Определены CI команды для проекта: syntax_check={bool(commands.get('build_command'))}, test={bool(commands.get('test_command'))}, quality={bool(commands.get('quality_command'))}")
            return {
                'success': True,
                'commands': commands
            }
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ Не удалось распарсить JSON: {e}. Ответ: {commands_text}")
            # Пытаемся определить команды эвристически
            return determine_ci_commands_heuristic(key_files, language, files, has_tests)
            
    except Exception as e:
        logger.error(f"❌ Ошибка при определении CI команд: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }

def determine_ci_commands_heuristic(key_files, language, files, has_tests=False):
    """Эвристическое определение команд CI на основе известных паттернов (только проверка синтаксиса, без сборки)"""
    commands = {
        'build_command': None,  # Используется для проверки синтаксиса
        'test_command': None,
        'quality_command': None,
        'working_directory': '.'
    }
    
    # Python - проверка синтаксиса без установки зависимостей
    if 'requirements.txt' in key_files or 'setup.py' in key_files or 'pyproject.toml' in key_files:
        # Проверяем синтаксис всех Python файлов
        commands['build_command'] = 'find . -name "*.py" -type f -exec python -m py_compile {} + || python -c "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]" $(find . -name "*.py" -type f)'
        if has_tests:
            # Проверяем наличие pytest
            if any('pytest' in f['path'].lower() or 'pytest.ini' in f['path'] for f in files if f['type'] == 'file'):
                commands['test_command'] = 'pytest'
            elif any('test' in f['path'].lower() for f in files if f['type'] == 'file'):
                commands['test_command'] = 'python -m unittest discover'
        commands['quality_command'] = 'pylint . || true'  # || true чтобы не падало на ошибках
    
    # Node.js - проверка синтаксиса
    elif 'package.json' in key_files:
        # Проверяем синтаксис JS файлов
        commands['build_command'] = 'find . -name "*.js" -type f -exec node --check {} + || true'
        if has_tests:
            commands['test_command'] = 'npm test'
        commands['quality_command'] = 'npm run lint || true'
    
    # TypeScript
    elif any(f['path'].endswith('tsconfig.json') for f in files if f['type'] == 'file'):
        commands['build_command'] = 'tsc --noEmit'
        if has_tests:
            commands['test_command'] = 'npm test'
        commands['quality_command'] = 'npm run lint || true'
    
    # Java (Maven) - проверка синтаксиса без компиляции
    elif 'pom.xml' in key_files:
        commands['build_command'] = 'mvn validate || mvn compiler:compile -DskipTests || true'
        if has_tests:
            commands['test_command'] = 'mvn test'
        commands['quality_command'] = 'mvn checkstyle:check || true'
    
    # Java (Gradle) - проверка синтаксиса
    elif 'build.gradle' in key_files:
        commands['build_command'] = './gradlew compileJava --dry-run || ./gradlew compileJava -x test || true'
        if has_tests:
            commands['test_command'] = './gradlew test'
        commands['quality_command'] = './gradlew check || true'
    
    # Rust - cargo check уже проверяет без сборки
    elif 'Cargo.toml' in key_files:
        commands['build_command'] = 'cargo check'
        if has_tests:
            commands['test_command'] = 'cargo test'
        commands['quality_command'] = 'cargo clippy || true'
    
    # Go - проверка синтаксиса
    elif 'go.mod' in key_files:
        commands['build_command'] = 'go build -o /dev/null ./... || go vet ./...'
        if has_tests:
            commands['test_command'] = 'go test ./...'
        commands['quality_command'] = 'golangci-lint run || true'
    
    # Makefile - если есть синтаксическая проверка
    if any(f['path'] == 'Makefile' for f in files):
        # Не используем make build, так как это сборка
        if has_tests and commands['test_command'] is None:
            commands['test_command'] = 'make test'
    
    return {
        'success': True,
        'commands': commands
    }

def run_ci_commands(owner, repo, branch, commands, installation_id=None):
    """
    Клонирует репозиторий и запускает CI команды локально
    ВАЖНО: build_command используется для проверки синтаксиса, а не для сборки проекта
    
    Args:
        owner: Владелец репозитория
        repo: Название репозитория
        branch: Ветка для клонирования
        commands: dict с командами (build_command - проверка синтаксиса, test_command, quality_command)
        installation_id: ID установки GitHub App
        
    Returns:
        dict с результатами выполнения CI
    """
    temp_dir = None
    try:
        logger.info(f"🔧 Запуск CI для {owner}/{repo} (ветка: {branch})...")
        
        # Создаем временную директорию
        temp_dir = tempfile.mkdtemp()
        logger.info(f"📁 Временная директория: {temp_dir}")
        
        # Получаем access token для клонирования
        if installation_id:
            access_token = get_installation_access_token(installation_id)
            clone_url = f'https://x-access-token:{access_token}@github.com/{owner}/{repo}.git'
        else:
            personal_token = os.getenv('GITHUB_TOKEN')
            if not personal_token:
                raise ValueError("Необходим либо GITHUB_INSTALLATION_ID, либо GITHUB_TOKEN")
            clone_url = f'https://x-access-token:{personal_token}@github.com/{owner}/{repo}.git'
        
        # Клонируем репозиторий
        logger.info(f"📥 Клонирование репозитория...")
        clone_result = subprocess.run(
            ['git', 'clone', '--depth', '1', '--branch', branch, clone_url, temp_dir],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if clone_result.returncode != 0:
            raise Exception(f"Ошибка клонирования репозитория: {clone_result.stderr}")
        
        logger.info(f"✅ Репозиторий клонирован")
        
        # Переходим в директорию проекта
        working_dir = commands.get('working_directory', '.')
        if working_dir != '.':
            work_path = os.path.join(temp_dir, working_dir)
        else:
            work_path = temp_dir
        
        results = {
            'build': {'success': None, 'output': '', 'error': ''},
            'test': {'success': None, 'output': '', 'error': ''},
            'quality': {'success': None, 'output': '', 'error': ''}
        }
        
        # Запускаем команду проверки синтаксиса (используется build_command для обратной совместимости)
        if commands.get('build_command'):
            logger.info(f"🔍 Проверка синтаксиса: {commands['build_command']}")
            syntax_result = subprocess.run(
                commands['build_command'],
                shell=True,
                cwd=work_path,
                capture_output=True,
                text=True,
                timeout=600
            )
            results['build'] = {
                'success': syntax_result.returncode == 0,
                'output': syntax_result.stdout,
                'error': syntax_result.stderr,
                'returncode': syntax_result.returncode
            }
            if syntax_result.returncode == 0:
                logger.info(f"✅ Проверка синтаксиса успешна")
            else:
                logger.warning(f"⚠️ Проверка синтаксиса выявила ошибки: {syntax_result.returncode}")
        
        # Запускаем тесты
        if commands.get('test_command'):
            logger.info(f"🧪 Запуск тестов: {commands['test_command']}")
            test_result = subprocess.run(
                commands['test_command'],
                shell=True,
                cwd=work_path,
                capture_output=True,
                text=True,
                timeout=600
            )
            results['test'] = {
                'success': test_result.returncode == 0,
                'output': test_result.stdout,
                'error': test_result.stderr,
                'returncode': test_result.returncode
            }
            if test_result.returncode == 0:
                logger.info(f"✅ Тесты прошли успешно")
            else:
                logger.warning(f"⚠️ Тесты завершились с ошибкой: {test_result.returncode}")
        
        # Запускаем проверку качества кода (опционально)
        if commands.get('quality_command'):
            logger.info(f"📊 Запуск проверки качества: {commands['quality_command']}")
            quality_result = subprocess.run(
                commands['quality_command'],
                shell=True,
                cwd=work_path,
                capture_output=True,
                text=True,
                timeout=300
            )
            results['quality'] = {
                'success': quality_result.returncode == 0,
                'output': quality_result.stdout,
                'error': quality_result.stderr,
                'returncode': quality_result.returncode
            }
            if quality_result.returncode == 0:
                logger.info(f"✅ Проверка качества прошла успешно")
            else:
                logger.info(f"ℹ️ Проверка качества завершилась с предупреждениями (это нормально)")
        
        return {
            'success': True,
            'results': results,
            'summary': {
                'build_passed': results['build']['success'] if results['build']['success'] is not None else True,
                'test_passed': results['test']['success'] if results['test']['success'] is not None else True,
                'quality_passed': results['quality']['success'] if results['quality']['success'] is not None else None
            }
        }
        
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Превышено время ожидания выполнения CI команд")
        return {
            'success': False,
            'error': 'Превышено время ожидания выполнения CI команд'
        }
    except Exception as e:
        logger.error(f"❌ Ошибка при выполнении CI команд: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        # Удаляем временную директорию
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"🗑️ Временная директория удалена")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось удалить временную директорию: {str(e)}")

# get_repository_name теперь импортируется из github.api

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
            'Анализ GitHub issues',
            'Автоматическое создание технических заданий',
            'Автоматическое исправление кода',
            'Создание Pull Request'
        ],
        'endpoints': {
            'GET /': 'Эта страница - информация о возможностях агента',
            'POST /fix-issue': 'Обработка issue: анализ, создание ТЗ и автоматическое исправление с созданием PR'
        },
        'usage': {
            'fix_issue': {
                'method': 'POST',
                'url': '/fix-issue',
                'body': {
                    'owner': 'owner',
                    'repo': 'repo',
                    'issue_url': 'https://github.com/owner/repo/issues/1'
                },
                'description': 'Обрабатывает issue: анализирует, создает ТЗ и автоматически исправляет код с созданием PR',
                'example': 'curl -X POST http://your-server/fix-issue -H "Content-Type: application/json" -d \'{"owner": "owner", "repo": "repo", "issue_url": "https://github.com/owner/repo/issues/1"}\''
            }
        }
    })

@app.route('/fix-issue', methods=['POST'])
def fix_issue():
    """
    Обрабатывает issue: анализирует, создает ТЗ и автоматически исправляет код с созданием PR
    Работает аналогично webhook при создании issue
    
    Принимает:
    - owner: владелец репозитория
    - repo: название репозитория
    - issue_url: ссылка на issue (можно использовать вместо owner/repo)
    """
    try:
        data = request.get_json() or {}
        
        # Получаем параметры
        owner = data.get('owner')
        repo = data.get('repo')
        issue_url = data.get('issue_url')
        
        # Если передан issue_url, извлекаем owner, repo и issue_number из него
        if issue_url:
            try:
                issue_parsed = parse_github_url(issue_url)
                if not owner:
                    owner = issue_parsed['owner']
                if not repo:
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
                    'error': f'Ошибка парсинга issue_url: {str(e)}'
                }), 400
        else:
            # Если issue_url не передан, нужно получить issue_number из данных
            issue_number = data.get('issue_number')
            if not issue_number:
                return jsonify({
                    'success': False,
                    'error': 'Необходимо указать либо issue_url, либо issue_number вместе с owner и repo'
                }), 400
        
        # Проверяем обязательные параметры
        if not owner or not repo:
            return jsonify({
                'success': False,
                'error': 'Необходимо указать owner и repo, либо issue_url'
            }), 400
        
        repo_full_name = f"{owner}/{repo}"
        
        # Автоматически определяем installation_id для репозитория
        installation_id = data.get('installation_id')
        if not installation_id:
            logger.info(f"🔍 Автоматический поиск installation_id для {owner}/{repo}...")
            installation_id = find_installation_id_for_repo(owner, repo)
        if not installation_id:
            installation_id = GITHUB_INSTALLATION_ID or None
        
        # Получаем данные issue
        logger.info(f"🔍 Получение данных issue #{issue_number} из {owner}/{repo}...")
        issue_data = get_issue_data(owner, repo, issue_number, installation_id)
        
        issue_title = issue_data['title']
        issue_body = issue_data['body'] or ''
        
        # Выводим в логи имя репозитория и название issue
        logger.info("=" * 60)
        logger.info(f"📝 ОБРАБОТКА ISSUE (fix-issue endpoint)")
        logger.info(f"📦 Репозиторий: {repo}")
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
                
                # Запускаем CI анализ репозитория
                logger.info("🔍 Анализирую репозиторий и определяю CI команды...")
                ci_commands_result = determine_ci_commands(owner, repo, installation_id)
                
                if not ci_commands_result.get('success'):
                    logger.warning(f"⚠️ Не удалось определить CI команды: {ci_commands_result.get('error')}")
                    ci_commands = {}
                    ci_before = {'summary': {'build_passed': None, 'test_passed': None, 'quality_passed': None}}
                else:
                    ci_commands = ci_commands_result.get('commands', {})
                    logger.info(f"✅ Определены CI команды: {ci_commands}")
                    
                    # Запускаем CI на основной ветке (до изменений)
                    logger.info("🧪 Запуск CI на основной ветке (до изменений)...")
                    repo_url = f'https://api.github.com/repos/{owner}/{repo}'
                    if installation_id:
                        access_token = get_installation_access_token(installation_id)
                        repo_headers = {
                            'Authorization': f'token {access_token}',
                            'Accept': 'application/vnd.github.v3+json'
                        }
                    else:
                        personal_token = os.getenv('GITHUB_TOKEN')
                        repo_headers = {
                            'Authorization': f'token {personal_token}',
                            'Accept': 'application/vnd.github.v3+json'
                        }
                    repo_response = requests.get(repo_url, headers=repo_headers)
                    default_branch = 'main'
                    if repo_response.status_code == 200:
                        default_branch = repo_response.json().get('default_branch', 'main')
                    
                    ci_before = run_ci_commands(owner, repo, default_branch, ci_commands, installation_id)
                    if not ci_before.get('success'):
                        logger.warning(f"⚠️ Не удалось запустить CI до изменений: {ci_before.get('error')}")
                        ci_before = {'summary': {'build_passed': None, 'test_passed': None, 'quality_passed': None}}
                    else:
                        logger.info(f"✅ CI до изменений: сборка={'✅' if ci_before.get('summary', {}).get('build_passed') else '❌'}, тесты={'✅' if ci_before.get('summary', {}).get('test_passed') else '❌'}")
                
                # Автоматически исправляем код, проверяем через Reviewer и создаем PR
                logger.info("🚀 Запускаю автоматическое исправление кода с проверкой через Reviewer...")
                try:
                    pr_result = auto_fix_and_create_pr_with_review(
                        owner=owner,
                        repo=repo,
                        issue_number=issue_number,
                        issue_title=issue_title,
                        issue_body=issue_body,
                        technical_spec=technical_spec,
                        ci_commands=ci_commands,
                        ci_before=ci_before,
                        installation_id=installation_id,
                        max_iterations=10
                    )
                    
                    if pr_result.get('success'):
                        logger.info(f"✅ Автоматическое исправление завершено успешно: {pr_result.get('pr_url')} (итераций: {pr_result.get('iteration', 1)})")
                    else:
                        logger.warning(f"⚠️ Автоматическое исправление не удалось: {pr_result.get('error')} (итераций: {pr_result.get('iteration', 0)})")
                except Exception as e:
                    logger.error(f"❌ Ошибка при автоматическом исправлении: {str(e)}")
                    pr_result = None
            else:
                logger.error(f"⚠️ Ошибка при создании ТЗ: {analysis_result.get('error', 'Неизвестная ошибка')}")
                technical_spec = None
                pr_result = None
                ci_before = None
                
        except Exception as e:
            logger.error(f"⚠️ Ошибка при создании ТЗ: {str(e)}")
            technical_spec = None
            pr_result = None
            ci_before = None
        
        response_data = {
            'success': True,
            'event': 'issue_fixed',
            'repository': {
                'name': repo,
                'full_name': repo_full_name
            },
            'issue': {
                'number': issue_number,
                'title': issue_title,
                'url': issue_data.get('url', f'https://github.com/{repo_full_name}/issues/{issue_number}'),
                'body': issue_body
            },
            'technical_spec': technical_spec if technical_spec else None,
            'message': f'Issue #{issue_number} "{issue_title}" обработана в репозитории {repo_full_name}'
        }
        
        if pr_result and pr_result.get('success'):
            response_data['pull_request'] = {
                'number': pr_result.get('pr_number'),
                'url': pr_result.get('pr_url'),
                'branch': pr_result.get('branch'),
                'fixed_files': pr_result.get('fixed_files', []),
                'iteration': pr_result.get('iteration', 1)
            }
            if pr_result.get('review'):
                response_data['review'] = {
                    'approved': pr_result['review'].get('approved'),
                    'reason': pr_result['review'].get('reason')
                }
            response_data['message'] += f'. Pull Request создан: {pr_result.get("pr_url")} (итераций: {pr_result.get("iteration", 1)})'
        elif pr_result:
            response_data['pr_error'] = pr_result.get('error')
            response_data['pr_iteration'] = pr_result.get('iteration', 0)
            if pr_result.get('review'):
                response_data['review'] = {
                    'approved': pr_result['review'].get('approved'),
                    'reason': pr_result['review'].get('reason'),
                    'issues': pr_result['review'].get('issues', [])
                }
        
        if ci_before:
            response_data['ci_before'] = {
                'build_passed': ci_before.get('summary', {}).get('build_passed'),
                'test_passed': ci_before.get('summary', {}).get('test_passed'),
                'quality_passed': ci_before.get('summary', {}).get('quality_passed')
            }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке issue: {str(e)}")
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
                    
                    # Запускаем CI анализ репозитория
                    logger.info("🔍 Анализирую репозиторий и определяю CI команды...")
                    ci_commands_result = determine_ci_commands(repo_owner, repo_repo, installation_id)
                    
                    if not ci_commands_result.get('success'):
                        logger.warning(f"⚠️ Не удалось определить CI команды: {ci_commands_result.get('error')}")
                        ci_commands = {}
                        ci_before = {'summary': {'build_passed': None, 'test_passed': None, 'quality_passed': None}}
                    else:
                        ci_commands = ci_commands_result.get('commands', {})
                        logger.info(f"✅ Определены CI команды: {ci_commands}")
                        
                        # Запускаем CI на основной ветке (до изменений)
                        logger.info("🧪 Запуск CI на основной ветке (до изменений)...")
                        repo_url = f'https://api.github.com/repos/{repo_owner}/{repo_repo}'
                        if installation_id:
                            access_token = get_installation_access_token(installation_id)
                            repo_headers = {
                                'Authorization': f'token {access_token}',
                                'Accept': 'application/vnd.github.v3+json'
                            }
                        else:
                            personal_token = os.getenv('GITHUB_TOKEN')
                            repo_headers = {
                                'Authorization': f'token {personal_token}',
                                'Accept': 'application/vnd.github.v3+json'
                            }
                        repo_response = requests.get(repo_url, headers=repo_headers)
                        default_branch = 'main'
                        if repo_response.status_code == 200:
                            default_branch = repo_response.json().get('default_branch', 'main')
                        
                        ci_before = run_ci_commands(repo_owner, repo_repo, default_branch, ci_commands, installation_id)
                        if not ci_before.get('success'):
                            logger.warning(f"⚠️ Не удалось запустить CI до изменений: {ci_before.get('error')}")
                            ci_before = {'summary': {'build_passed': None, 'test_passed': None, 'quality_passed': None}}
                        else:
                            logger.info(f"✅ CI до изменений: сборка={'✅' if ci_before.get('summary', {}).get('build_passed') else '❌'}, тесты={'✅' if ci_before.get('summary', {}).get('test_passed') else '❌'}")
                    
                    # Автоматически исправляем код, проверяем через Reviewer и создаем PR
                    logger.info("🚀 Запускаю автоматическое исправление кода с проверкой через Reviewer...")
                    try:
                        pr_result = auto_fix_and_create_pr_with_review(
                            owner=repo_owner,
                            repo=repo_repo,
                            issue_number=issue_number,
                            issue_title=issue_title,
                            issue_body=issue_body,
                            technical_spec=technical_spec,
                            ci_commands=ci_commands,
                            ci_before=ci_before,
                            installation_id=installation_id,
                            max_iterations=10
                        )
                        
                        if pr_result.get('success'):
                            logger.info(f"✅ Автоматическое исправление завершено успешно: {pr_result.get('pr_url')} (итераций: {pr_result.get('iteration', 1)})")
                        else:
                            logger.warning(f"⚠️ Автоматическое исправление не удалось: {pr_result.get('error')} (итераций: {pr_result.get('iteration', 0)})")
                    except Exception as e:
                        logger.error(f"❌ Ошибка при автоматическом исправлении: {str(e)}")
                        pr_result = None
                else:
                    logger.error(f"⚠️ Ошибка при создании ТЗ: {analysis_result.get('error', 'Неизвестная ошибка')}")
                    technical_spec = None
                    pr_result = None
                    ci_before = None
                    
            except Exception as e:
                logger.error(f"⚠️ Ошибка при создании ТЗ: {str(e)}")
                technical_spec = None
                pr_result = None
                ci_before = None
            
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
                    'fixed_files': pr_result.get('fixed_files', []),
                    'iteration': pr_result.get('iteration', 1)
                }
                if pr_result.get('review'):
                    response_data['review'] = {
                        'approved': pr_result['review'].get('approved'),
                        'reason': pr_result['review'].get('reason')
                    }
                response_data['message'] += f'. Pull Request создан: {pr_result.get("pr_url")} (итераций: {pr_result.get("iteration", 1)})'
            elif pr_result:
                response_data['pr_error'] = pr_result.get('error')
                response_data['pr_iteration'] = pr_result.get('iteration', 0)
                if pr_result.get('review'):
                    response_data['review'] = {
                        'approved': pr_result['review'].get('approved'),
                        'reason': pr_result['review'].get('reason'),
                        'issues': pr_result['review'].get('issues', [])
                    }
            
            if ci_before:
                response_data['ci_before'] = {
                    'build_passed': ci_before.get('summary', {}).get('build_passed'),
                    'test_passed': ci_before.get('summary', {}).get('test_passed'),
                    'quality_passed': ci_before.get('summary', {}).get('quality_passed')
                }
            
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
