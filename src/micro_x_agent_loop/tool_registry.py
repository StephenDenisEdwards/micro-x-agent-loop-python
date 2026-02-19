from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tools.bash_tool import BashTool
from micro_x_agent_loop.tools.read_file_tool import ReadFileTool
from micro_x_agent_loop.tools.write_file_tool import WriteFileTool
from micro_x_agent_loop.tools.append_file_tool import AppendFileTool
from micro_x_agent_loop.tools.linkedin.linkedin_jobs_tool import LinkedInJobsTool
from micro_x_agent_loop.tools.linkedin.linkedin_job_detail_tool import LinkedInJobDetailTool
from micro_x_agent_loop.tools.web.web_fetch_tool import WebFetchTool


def get_all(
    working_directory: str | None = None,
    google_client_id: str | None = None,
    google_client_secret: str | None = None,
    anthropic_admin_api_key: str | None = None,
    brave_api_key: str | None = None,
) -> list[Tool]:
    tools: list[Tool] = [
        BashTool(working_directory),
        ReadFileTool(working_directory),
        WriteFileTool(working_directory),
        AppendFileTool(working_directory),
        LinkedInJobsTool(),
        LinkedInJobDetailTool(),
        WebFetchTool(),
    ]

    if google_client_id and google_client_secret:
        from micro_x_agent_loop.tools.gmail.gmail_search_tool import GmailSearchTool
        from micro_x_agent_loop.tools.gmail.gmail_read_tool import GmailReadTool
        from micro_x_agent_loop.tools.gmail.gmail_send_tool import GmailSendTool

        tools.append(GmailSearchTool(google_client_id, google_client_secret))
        tools.append(GmailReadTool(google_client_id, google_client_secret))
        tools.append(GmailSendTool(google_client_id, google_client_secret))

        from micro_x_agent_loop.tools.calendar.calendar_list_events_tool import CalendarListEventsTool
        from micro_x_agent_loop.tools.calendar.calendar_create_event_tool import CalendarCreateEventTool
        from micro_x_agent_loop.tools.calendar.calendar_get_event_tool import CalendarGetEventTool

        tools.append(CalendarListEventsTool(google_client_id, google_client_secret))
        tools.append(CalendarCreateEventTool(google_client_id, google_client_secret))
        tools.append(CalendarGetEventTool(google_client_id, google_client_secret))

        from micro_x_agent_loop.tools.contacts.contacts_search_tool import ContactsSearchTool
        from micro_x_agent_loop.tools.contacts.contacts_list_tool import ContactsListTool
        from micro_x_agent_loop.tools.contacts.contacts_get_tool import ContactsGetTool
        from micro_x_agent_loop.tools.contacts.contacts_create_tool import ContactsCreateTool
        from micro_x_agent_loop.tools.contacts.contacts_update_tool import ContactsUpdateTool
        from micro_x_agent_loop.tools.contacts.contacts_delete_tool import ContactsDeleteTool

        tools.append(ContactsSearchTool(google_client_id, google_client_secret))
        tools.append(ContactsListTool(google_client_id, google_client_secret))
        tools.append(ContactsGetTool(google_client_id, google_client_secret))
        tools.append(ContactsCreateTool(google_client_id, google_client_secret))
        tools.append(ContactsUpdateTool(google_client_id, google_client_secret))
        tools.append(ContactsDeleteTool(google_client_id, google_client_secret))

    if anthropic_admin_api_key:
        from micro_x_agent_loop.tools.anthropic.anthropic_usage_tool import AnthropicUsageTool

        tools.append(AnthropicUsageTool(anthropic_admin_api_key))

    if brave_api_key:
        from micro_x_agent_loop.tools.web.brave_search_provider import BraveSearchProvider
        from micro_x_agent_loop.tools.web.web_search_tool import WebSearchTool

        tools.append(WebSearchTool(BraveSearchProvider(brave_api_key)))

    return tools
