"""ORM models. Every model must be imported here so Alembic autogenerate sees it."""

from cara.models.admin_settings import AdminSetting
from cara.models.agent_run import AgentRun
from cara.models.audit import AuditLog
from cara.models.budget import Budget, Expense
from cara.models.calendar_event import CalendarEvent
from cara.models.cda import CdaContentItem, CdaDomainTrust, CdaQueryLog, CdaUserPreference
from cara.models.conversation import Conversation, Message
from cara.models.device import Device
from cara.models.device_alias import DeviceAlias
from cara.models.device_permission import DevicePermission
from cara.models.email_proposal import EmailLearningSignal, EmailProposal
from cara.models.event import Event
from cara.models.fact import Fact
from cara.models.file import UploadedFile
from cara.models.habit import HabitCandidate
from cara.models.note import Note
from cara.models.oauth_credentials import OAuthCredentials
from cara.models.presence_event import PresenceEvent
from cara.models.push_subscription import PushSubscription
from cara.models.shopping import ShoppingItem
from cara.models.skill import Skill
from cara.models.task import Task
from cara.models.telegram_chat import TelegramChatMapping
from cara.models.tool_metric import ToolCallMetric
from cara.models.user import User
from cara.models.wallet_layout import WalletLayout
from cara.models.workflow_trust import WorkflowTrust

__all__ = [
    "AdminSetting",
    "AgentRun",
    "AuditLog",
    "Budget",
    "CalendarEvent",
    "CdaContentItem",
    "CdaDomainTrust",
    "CdaQueryLog",
    "CdaUserPreference",
    "Conversation",
    "Device",
    "DeviceAlias",
    "DevicePermission",
    "EmailLearningSignal",
    "EmailProposal",
    "Event",
    "Expense",
    "Fact",
    "HabitCandidate",
    "Message",
    "Note",
    "OAuthCredentials",
    "PresenceEvent",
    "PushSubscription",
    "ShoppingItem",
    "Skill",
    "Task",
    "TelegramChatMapping",
    "ToolCallMetric",
    "UploadedFile",
    "User",
    "WalletLayout",
    "WorkflowTrust",
]
