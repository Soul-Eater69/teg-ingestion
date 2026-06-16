"""Jira source integration: client protocol + records + REST implementation."""

from teg.integrations.jira.client import JiraAttachment, JiraClient, JiraTicket
from teg.integrations.jira.rest_client import JiraRestClient, build_jira_client

__all__ = [
    "JiraAttachment",
    "JiraClient",
    "JiraTicket",
    "JiraRestClient",
    "build_jira_client",
]
