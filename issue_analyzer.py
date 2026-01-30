"""
Агент на LangGraph для анализа issue и создания технического задания
"""
import os
from typing import TypedDict, Annotated
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# Типы для состояния графа
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    issue_title: str
    issue_body: str
    repository_name: str
    technical_spec: str


def create_issue_analyzer_agent():
    """
    Создает агента на LangGraph для анализа issue
    """
    # Инициализируем LLM
    llm = ChatOpenAI(
        model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
        temperature=0.3,
        api_key=os.getenv('OPENAI_API_KEY')
    )
    
    # Промпт для анализа issue
    analysis_prompt = ChatPromptTemplate.from_messages([
        ("system", """Ты - опытный технический аналитик, который превращает описания проблем (issue) 
в четкие технические задания для программистов.

Твоя задача:
1. Проанализировать описание issue
2. Выделить ключевые требования
3. Определить технические детали
4. Создать структурированное ТЗ

Формат ТЗ должен включать:
- Цель задачи
- Описание проблемы/требования
- Технические требования
- Ожидаемый результат
- Критерии приемки (если возможно)

Будь конкретным и технически точным."""),
        MessagesPlaceholder(variable_name="messages"),
    ])
    
    # Узел для анализа issue
    def analyze_issue(state: AgentState):
        """Анализирует issue и создает ТЗ"""
        issue_title = state.get('issue_title', '')
        issue_body = state.get('issue_body', '')
        repo_name = state.get('repository_name', '')
        
        # Формируем запрос для анализа
        issue_text = f"""
РЕПОЗИТОРИЙ: {repo_name}

НАЗВАНИЕ ISSUE: {issue_title}

ОПИСАНИЕ ISSUE:
{issue_body if issue_body else 'Описание отсутствует'}
"""
        
        # Получаем ответ от LLM
        messages = analysis_prompt.invoke({
            "messages": [HumanMessage(content=issue_text)]
        })
        
        response = llm.invoke(messages)
        technical_spec = response.content
        
        return {
            "technical_spec": technical_spec,
            "messages": [response]
        }
    
    # Создаем граф
    workflow = StateGraph(AgentState)
    
    # Добавляем узлы
    workflow.add_node("analyze", analyze_issue)
    
    # Определяем поток
    workflow.set_entry_point("analyze")
    workflow.add_edge("analyze", END)
    
    # Компилируем граф
    app = workflow.compile()
    
    return app


def analyze_issue_to_spec(issue_title: str, issue_body: str, repository_name: str) -> str:
    """
    Анализирует issue и возвращает техническое задание
    
    Args:
        issue_title: Название issue
        issue_body: Описание issue
        repository_name: Имя репозитория
        
    Returns:
        Строка с техническим заданием
    """
    try:
        # Проверяем наличие API ключа
        if not os.getenv('OPENAI_API_KEY'):
            return "⚠️ Ошибка: OPENAI_API_KEY не установлен. Установите API ключ в .env файле."
        
        # Создаем агента
        agent = create_issue_analyzer_agent()
        
        # Начальное состояние
        initial_state = {
            "messages": [],
            "issue_title": issue_title,
            "issue_body": issue_body or "Описание отсутствует",
            "repository_name": repository_name,
            "technical_spec": ""
        }
        
        # Запускаем агента
        result = agent.invoke(initial_state)
        
        # Извлекаем техническое задание
        technical_spec = result.get('technical_spec', 'Не удалось создать ТЗ')
        
        return technical_spec
        
    except Exception as e:
        return f"⚠️ Ошибка при анализе issue: {str(e)}"
