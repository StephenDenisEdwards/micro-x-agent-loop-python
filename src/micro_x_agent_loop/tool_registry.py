from micro_x_agent_loop.tool import Tool
from micro_x_agent_loop.tools.bash_tool import BashTool
from micro_x_agent_loop.tools.read_file_tool import ReadFileTool
from micro_x_agent_loop.tools.write_file_tool import WriteFileTool
from micro_x_agent_loop.tools.linkedin.linkedin_jobs_tool import LinkedInJobsTool
from micro_x_agent_loop.tools.linkedin.linkedin_job_detail_tool import LinkedInJobDetailTool


def get_all(
    documents_directory: str | None = None,
    working_directory: str | None = None,
    google_client_id: str | None = None,
    google_client_secret: str | None = None,
) -> list[Tool]:
    tools: list[Tool] = [
        BashTool(working_directory),
        ReadFileTool(documents_directory, working_directory),
        WriteFileTool(working_directory),
        LinkedInJobsTool(),
        LinkedInJobDetailTool(),
    ]

    if google_client_id and google_client_secret:
        from micro_x_agent_loop.tools.gmail.gmail_search_tool import GmailSearchTool
        from micro_x_agent_loop.tools.gmail.gmail_read_tool import GmailReadTool
        from micro_x_agent_loop.tools.gmail.gmail_send_tool import GmailSendTool

        tools.append(GmailSearchTool(google_client_id, google_client_secret))
        tools.append(GmailReadTool(google_client_id, google_client_secret))
        tools.append(GmailSendTool(google_client_id, google_client_secret))

    return tools
