from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tools.append_file_tool import AppendFileTool
from micro_x_agent_loop.tools.bash_tool import BashTool
from micro_x_agent_loop.tools.linkedin.linkedin_job_detail_tool import LinkedInJobDetailTool
from micro_x_agent_loop.tools.linkedin.linkedin_jobs_tool import LinkedInJobsTool
from micro_x_agent_loop.tools.read_file_tool import ReadFileTool
from micro_x_agent_loop.tools.web.web_fetch_tool import WebFetchTool
from micro_x_agent_loop.tools.write_file_tool import WriteFileTool


@dataclass(frozen=True)
class ToolGroup:
    enabled: Callable[[dict], bool]
    build: Callable[[dict], list[Tool]]


def _always(_: dict) -> bool:
    return True


def _base_tools(ctx: dict) -> list[Tool]:
    working_directory = ctx["working_directory"]
    return [
        BashTool(working_directory),
        ReadFileTool(working_directory),
        WriteFileTool(working_directory),
        AppendFileTool(working_directory),
        LinkedInJobsTool(),
        LinkedInJobDetailTool(),
        WebFetchTool(),
    ]


def _google_enabled(ctx: dict) -> bool:
    return bool(ctx.get("google_client_id") and ctx.get("google_client_secret"))


def _google_tools(ctx: dict) -> list[Tool]:
    google_client_id = ctx["google_client_id"]
    google_client_secret = ctx["google_client_secret"]

    from micro_x_agent_loop.tools.calendar.calendar_create_event_tool import CalendarCreateEventTool
    from micro_x_agent_loop.tools.calendar.calendar_get_event_tool import CalendarGetEventTool
    from micro_x_agent_loop.tools.calendar.calendar_list_events_tool import CalendarListEventsTool
    from micro_x_agent_loop.tools.contacts.contacts_create_tool import ContactsCreateTool
    from micro_x_agent_loop.tools.contacts.contacts_delete_tool import ContactsDeleteTool
    from micro_x_agent_loop.tools.contacts.contacts_get_tool import ContactsGetTool
    from micro_x_agent_loop.tools.contacts.contacts_list_tool import ContactsListTool
    from micro_x_agent_loop.tools.contacts.contacts_search_tool import ContactsSearchTool
    from micro_x_agent_loop.tools.contacts.contacts_update_tool import ContactsUpdateTool
    from micro_x_agent_loop.tools.gmail.gmail_read_tool import GmailReadTool
    from micro_x_agent_loop.tools.gmail.gmail_search_tool import GmailSearchTool
    from micro_x_agent_loop.tools.gmail.gmail_send_tool import GmailSendTool

    return [
        GmailSearchTool(google_client_id, google_client_secret),
        GmailReadTool(google_client_id, google_client_secret),
        GmailSendTool(google_client_id, google_client_secret),
        CalendarListEventsTool(google_client_id, google_client_secret),
        CalendarCreateEventTool(google_client_id, google_client_secret),
        CalendarGetEventTool(google_client_id, google_client_secret),
        ContactsSearchTool(google_client_id, google_client_secret),
        ContactsListTool(google_client_id, google_client_secret),
        ContactsGetTool(google_client_id, google_client_secret),
        ContactsCreateTool(google_client_id, google_client_secret),
        ContactsUpdateTool(google_client_id, google_client_secret),
        ContactsDeleteTool(google_client_id, google_client_secret),
    ]


def _anthropic_admin_enabled(ctx: dict) -> bool:
    return bool(ctx.get("anthropic_admin_api_key"))


def _anthropic_admin_tools(ctx: dict) -> list[Tool]:
    from micro_x_agent_loop.tools.anthropic.anthropic_usage_tool import AnthropicUsageTool

    return [AnthropicUsageTool(ctx["anthropic_admin_api_key"])]


def _web_search_enabled(ctx: dict) -> bool:
    return bool(ctx.get("brave_api_key"))


def _web_search_tools(ctx: dict) -> list[Tool]:
    from micro_x_agent_loop.tools.web.brave_search_provider import BraveSearchProvider
    from micro_x_agent_loop.tools.web.web_search_tool import WebSearchTool

    return [WebSearchTool(BraveSearchProvider(ctx["brave_api_key"]))]


def _github_enabled(ctx: dict) -> bool:
    return bool(ctx.get("github_token"))


def _github_tools(ctx: dict) -> list[Tool]:
    github_token = ctx["github_token"]

    from micro_x_agent_loop.tools.github.github_create_issue_tool import GitHubCreateIssueTool
    from micro_x_agent_loop.tools.github.github_create_pr_tool import GitHubCreatePRTool
    from micro_x_agent_loop.tools.github.github_get_file_tool import GitHubGetFileTool
    from micro_x_agent_loop.tools.github.github_get_pr_tool import GitHubGetPRTool
    from micro_x_agent_loop.tools.github.github_list_issues_tool import GitHubListIssuesTool
    from micro_x_agent_loop.tools.github.github_list_prs_tool import GitHubListPRsTool
    from micro_x_agent_loop.tools.github.github_list_repos_tool import GitHubListReposTool
    from micro_x_agent_loop.tools.github.github_search_code_tool import GitHubSearchCodeTool

    return [
        GitHubListPRsTool(github_token),
        GitHubGetPRTool(github_token),
        GitHubCreateIssueTool(github_token),
        GitHubListIssuesTool(github_token),
        GitHubCreatePRTool(github_token),
        GitHubGetFileTool(github_token),
        GitHubSearchCodeTool(github_token),
        GitHubListReposTool(github_token),
    ]


_GROUPS = [
    ToolGroup(enabled=_always, build=_base_tools),
    ToolGroup(enabled=_google_enabled, build=_google_tools),
    ToolGroup(enabled=_anthropic_admin_enabled, build=_anthropic_admin_tools),
    ToolGroup(enabled=_web_search_enabled, build=_web_search_tools),
    ToolGroup(enabled=_github_enabled, build=_github_tools),
]


def get_all(
    working_directory: str | None = None,
    google_client_id: str | None = None,
    google_client_secret: str | None = None,
    anthropic_admin_api_key: str | None = None,
    brave_api_key: str | None = None,
    github_token: str | None = None,
) -> list[Tool]:
    ctx = {
        "working_directory": working_directory,
        "google_client_id": google_client_id,
        "google_client_secret": google_client_secret,
        "anthropic_admin_api_key": anthropic_admin_api_key,
        "brave_api_key": brave_api_key,
        "github_token": github_token,
    }

    tools: list[Tool] = []
    for group in _GROUPS:
        if group.enabled(ctx):
            tools.extend(group.build(ctx))
    return tools
