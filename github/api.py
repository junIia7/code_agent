"""
GitHub API функции для получения данных
"""
import os
import logging
import requests
from .auth import get_installation_access_token

logger = logging.getLogger('github-app')


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
            'title': issue_data['title'],
            'body': issue_data['body'] or '',
            'state': issue_data['state'],
            'number': issue_data['number'],
            'user': issue_data['user']['login'],
            'created_at': issue_data['created_at'],
            'updated_at': issue_data['updated_at']
        }
    else:
        raise Exception(f"Ошибка получения issue: {response.status_code} - {response.text}")


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


def get_repository_structure(owner, repo, branch='main', installation_id=None, max_depth=2):
    """
    Получает структуру репозитория через GitHub API
    
    Args:
        owner: Владелец репозитория
        repo: Название репозитория
        branch: Ветка (по умолчанию 'main')
        installation_id: ID установки GitHub App (опционально)
        max_depth: Максимальная глубина вложенности (по умолчанию 2)
        
    Returns:
        dict с информацией о структуре репозитория
    """
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
    
    def get_tree_recursive(path='', depth=0):
        """Рекурсивно получает дерево файлов"""
        if depth > max_depth:
            return []
        
        url = f'https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}'
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            return []
        
        items = response.json()
        result = []
        
        for item in items:
            if item['type'] == 'file':
                result.append({
                    'path': item['path'],
                    'type': 'file',
                    'size': item.get('size', 0)
                })
            elif item['type'] == 'dir' and depth < max_depth:
                result.append({
                    'path': item['path'],
                    'type': 'dir',
                    'children': get_tree_recursive(item['path'], depth + 1)
                })
        
        return result
    
    try:
        structure = get_tree_recursive()
        return {
            'success': True,
            'structure': structure,
            'branch': branch
        }
    except Exception as e:
        logger.error(f"❌ Ошибка при получении структуры репозитория: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'structure': []
        }
