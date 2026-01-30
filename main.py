import os
import jwt
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv
from issue_analyzer import analyze_issue_to_spec

# Загружаем переменные окружения из .env файла
load_dotenv()

app = Flask(__name__)

# Конфигурация GitHub App
GITHUB_APP_ID = os.getenv('GITHUB_APP_ID')
GITHUB_APP_PRIVATE_KEY = os.getenv('GITHUB_APP_PRIVATE_KEY')
GITHUB_INSTALLATION_ID = os.getenv('GITHUB_INSTALLATION_ID', '')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')

def get_github_app_token():
    """
    Генерирует JWT токен для GitHub App
    """
    if not GITHUB_APP_ID or not GITHUB_APP_PRIVATE_KEY:
        raise ValueError("GITHUB_APP_ID и GITHUB_APP_PRIVATE_KEY должны быть установлены")
    
    # Парсим приватный ключ
    private_key = GITHUB_APP_PRIVATE_KEY.replace('\\n', '\n')
    
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

def verify_webhook_signature(payload_body, signature_header):
    """
    Проверяет подпись webhook от GitHub используя HMAC SHA256
    """
    if not WEBHOOK_SECRET:
        print("⚠️  ВНИМАНИЕ: WEBHOOK_SECRET не установлен, проверка подписи пропущена")
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
    Главная страница
    """
    return jsonify({
        'message': 'GitHub App для получения информации о репозитории',
        'endpoints': {
            '/repo/<owner>/<repo>': 'Получить информацию о репозитории',
            '/webhook': 'Webhook для GitHub событий'
        }
    })

@app.route('/repo/<owner>/<repo>', methods=['GET'])
def get_repo_info(owner, repo):
    """
    Получает информацию о репозитории
    """
    try:
        installation_id = request.args.get('installation_id', GITHUB_INSTALLATION_ID) or None
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
            print("❌ Ошибка: Неверная подпись webhook")
            return jsonify({
                'error': 'Неверная подпись webhook'
            }), 401
        
        # Парсим JSON payload
        payload = request.json
        event_type = request.headers.get('X-GitHub-Event')
        
        print(f"📥 Получено событие: {event_type}")
        
        # Обработка установки GitHub App
        if event_type == 'installation' and payload.get('action') == 'created':
            installation_id = payload['installation']['id']
            print(f"✅ GitHub App установлен! Installation ID: {installation_id}")
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
            
            # Выводим в консоль имя репозитория и название issue
            print("=" * 60)
            print(f"📝 СОЗДАНА НОВАЯ ISSUE")
            print(f"📦 Репозиторий: {repo_name}")
            print(f"🔗 Полное имя: {repo_full_name}")
            print(f"#️⃣  Номер issue: #{issue_number}")
            print(f"📌 Название issue: {issue_title}")
            print("=" * 60)
            
            # Анализируем issue и создаем ТЗ
            print("\n🤖 Анализирую issue и создаю техническое задание...")
            try:
                technical_spec = analyze_issue_to_spec(
                    issue_title=issue_title,
                    issue_body=issue_body,
                    repository_name=repo_full_name
                )
                
                # Выводим ТЗ в консоль с красивым форматированием
                print("\n" + "=" * 80)
                print("📋 ТЕХНИЧЕСКОЕ ЗАДАНИЕ")
                print("=" * 80)
                print(technical_spec)
                print("=" * 80 + "\n")
                
            except Exception as e:
                print(f"⚠️ Ошибка при создании ТЗ: {str(e)}")
                technical_spec = None
            
            return jsonify({
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
            })
        
        # Обработка других событий репозитория
        if 'repository' in payload:
            repo = payload['repository']
            repo_name = repo.get('name')
            repo_full_name = repo.get('full_name')
            
            print(f"📦 Событие {event_type} для репозитория: {repo_full_name}")
            
            return jsonify({
                'event': event_type,
                'repository_name': repo_name,
                'repository_full_name': repo_full_name,
                'message': f'Получено событие {event_type} для репозитория {repo_full_name}'
            })
        
        print(f"ℹ️  Необработанное событие: {event_type}")
        return jsonify({
            'event': event_type,
            'message': 'Webhook получен'
        })
    except Exception as e:
        print(f"❌ Ошибка обработки webhook: {str(e)}")
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
    app.run(host='0.0.0.0', port=port, debug=True)
