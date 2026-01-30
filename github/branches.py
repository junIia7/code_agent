"""
GitHub функции для работы с ветками и Pull Requests
"""
import os
import logging
import requests
import traceback
from .auth import get_installation_access_token

logger = logging.getLogger('github-app')


def create_pr_comment(owner, repo, pr_number, comment_body, installation_id=None):
    """Создает комментарий в Pull Request"""
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
        
        comment_url = f'https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments'
        comment_data = {
            'body': comment_body
        }
        
        comment_response = requests.post(comment_url, headers=headers, json=comment_data)
        
        if comment_response.status_code not in [201, 200]:
            raise Exception(f"Не удалось создать комментарий: {comment_response.status_code} - {comment_response.text}")
        
        logger.info(f"✅ Комментарий добавлен в PR #{pr_number}")
        return {
            'success': True,
            'comment_id': comment_response.json().get('id')
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании комментария в PR: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def create_pr_from_branch(owner, repo, branch_name, default_branch, issue_number, 
                          technical_spec, fixed_files, failed_files, installation_id=None, pr_number=None):
    """Создает Pull Request из существующей ветки или возвращает существующий PR"""
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
        
        # Если передан pr_number, значит PR уже существует
        if pr_number:
            pr_get_url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}'
            pr_get_response = requests.get(pr_get_url, headers=headers)
            if pr_get_response.status_code == 200:
                pr_data = pr_get_response.json()
                pr_num = pr_data.get('number', pr_number)
                html_url = pr_data.get('html_url') or f'https://github.com/{owner}/{repo}/pull/{pr_num}'
                logger.info(f"ℹ️  Используется существующий PR: {html_url}")
                return {
                    'success': True,
                    'pr_number': pr_num,
                    'pr_url': html_url,
                    'branch': branch_name
                }
        
        # Проверяем существование ветки перед созданием PR
        branch_check_url = f'https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{branch_name}'
        branch_check_response = requests.get(branch_check_url, headers=headers)
        
        if branch_check_response.status_code != 200:
            # Ветка не существует, создаем её
            logger.info(f"🌿 Ветка {branch_name} не существует, создаем её...")
            ref_url = f'https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{default_branch}'
            ref_response = requests.get(ref_url, headers=headers)
            
            if ref_response.status_code != 200:
                raise Exception(f"Не удалось получить информацию о ветке {default_branch}: {ref_response.status_code}")
            
            base_sha = ref_response.json()['object']['sha']
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
        
        # Создаем PR
        pr_response = requests.post(pr_url, headers=headers, json=pr_data)

        # Успешное создание PR
        if pr_response.status_code == 201:
            try:
                pr_response_data = pr_response.json()
                pr_num = pr_response_data.get('number')
                if not pr_num:
                    raise ValueError("Ответ не содержит номер PR")
                html_url = pr_response_data.get('html_url') or f'https://github.com/{owner}/{repo}/pull/{pr_num}'
                logger.info(f"✅ Pull Request создан: #{pr_num} - {html_url}")
                
                return {
                    'success': True,
                    'pr_number': pr_num,
                    'pr_url': html_url,
                    'branch': branch_name
                }
            except (KeyError, ValueError, TypeError) as json_error:
                logger.error(f"❌ Ошибка парсинга ответа PR: {str(json_error)}")
                logger.error(f"❌ Ответ сервера: {pr_response.text[:500]}")
                raise Exception(f"Не удалось распарсить ответ при создании PR: {str(json_error)}")

        # Ошибка 422 может означать либо что PR уже существует, либо что ветка не существует
        elif pr_response.status_code == 422:
            error_text = pr_response.text.lower()
            
            # Проверяем, существует ли ветка
            branch_check_url = f'https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{branch_name}'
            branch_check_response = requests.get(branch_check_url, headers=headers)
            
            if branch_check_response.status_code != 200:
                # Ветка не существует - это основная причина ошибки
                logger.error(f"❌ Ветка {branch_name} не существует. Нельзя создать PR без ветки.")
                raise Exception(f"Ветка {branch_name} не существует. Сначала создайте ветку и закоммитьте изменения, затем создайте PR.")
            
            # Ветка существует, значит проблема в том, что PR уже существует
            # Получаем существующий PR - сначала пробуем открытые
            existing_prs_url = f'https://api.github.com/repos/{owner}/{repo}/pulls?head={owner}:{branch_name}&state=open'
            existing_prs_response = requests.get(existing_prs_url, headers=headers)
            
            if existing_prs_response.status_code == 200:
                existing_prs = existing_prs_response.json()
                if existing_prs:
                    existing_pr_data = existing_prs[0]
                    pr_num = existing_pr_data.get('number')
                    html_url = existing_pr_data.get('html_url') or f'https://github.com/{owner}/{repo}/pull/{pr_num}'
                    logger.info(f"ℹ️  PR уже существует (открыт): {html_url}")
                    return {
                        'success': True,
                        'pr_number': pr_num,
                        'pr_url': html_url,
                        'branch': branch_name
                    }
            
            # Если не нашли среди открытых, пробуем все (включая закрытые/мердженные)
            existing_prs_url_all = f'https://api.github.com/repos/{owner}/{repo}/pulls?head={owner}:{branch_name}&state=all'
            existing_prs_response_all = requests.get(existing_prs_url_all, headers=headers)
            
            if existing_prs_response_all.status_code == 200:
                existing_prs_all = existing_prs_response_all.json()
                if existing_prs_all:
                    existing_pr_data = existing_prs_all[0]
                    pr_num = existing_pr_data.get('number')
                    html_url = existing_pr_data.get('html_url') or f'https://github.com/{owner}/{repo}/pull/{pr_num}'
                    state = existing_pr_data.get('state', 'unknown')
                    logger.info(f"ℹ️  PR уже существует (статус: {state}): {html_url}")
                    return {
                        'success': True,
                        'pr_number': pr_num,
                        'pr_url': html_url,
                        'branch': branch_name
                    }
            
            # Логируем детали для отладки
            logger.error(f"❌ Не удалось получить существующий PR для ветки {branch_name}")
            logger.error(f"❌ Ответ GitHub API (422): {pr_response.text[:500]}")
            if existing_prs_response.status_code != 200:
                logger.error(f"❌ Ошибка при запросе открытых PR: {existing_prs_response.status_code} - {existing_prs_response.text[:500]}")
            if existing_prs_response_all.status_code != 200:
                logger.error(f"❌ Ошибка при запросе всех PR: {existing_prs_response_all.status_code} - {existing_prs_response_all.text[:500]}")
            
            # Не удалось получить существующий PR
            raise Exception(f"PR уже существует (статус 422), но не удалось его получить. Проверьте ветку {branch_name} в репозитории {owner}/{repo}")

        # Другие ошибки
        else:
            error_text = pr_response.text
            logger.error(f"❌ Ошибка создания PR: {pr_response.status_code} - {error_text}")
            raise Exception(f"Не удалось создать PR: {pr_response.status_code} - {error_text}")
    
    except Exception as e:
        logger.error(f"❌ Ошибка при создании PR: {str(e)}")
        logger.error(f"❌ Детали ошибки: {traceback.format_exc()}")
        raise
