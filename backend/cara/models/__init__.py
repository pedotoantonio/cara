"""ORM models. Every model must be imported here so Alembic autogenerate sees it."""

from cara.models.admin_settings import AdminSetting
from cara.models.audit import AuditLog
from cara.models.cda import CdaContentItem, CdaDomainTrust, CdaQueryLog, CdaUserPreference
from cara.models.conversation import Conversation, Message
from cara.models.device import Device
from cara.models.device_permission import DevicePermission
from cara.models.event import Event
from cara.models.fact import Fact
from cara.models.file import UploadedFile
from cara.models.habit import HabitCandidate
from cara.models.note import Note
from cara.models.shopping import ShoppingItem
from cara.models.skill import Skill
from cara.models.task import Task
from cara.models.tool_metric import ToolCallMetric
from cara.models.user import User

__all__ = [
    "AdminSetting",
    "AuditLog",
    "CdaContentItem",
    "CdaDomainTrust",
    "CdaQueryLog",
    "CdaUserPreference",
    "Conversation",
    "Device",
    "DevicePermission",
    "Event",
    "Fact",
    "HabitCandidate",
    "Message",
    "Note",
    "ShoppingItem",
    "Skill",
    "Task",
    "ToolCallMetric",
    "UploadedFile",
    "User",
]
