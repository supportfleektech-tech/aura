"""Routes package — all FastAPI routers extracted from domain.py."""
from .tasks import tasks_r
from .clients import clients_r
from .projects import projects_r, add_milestone
from .personal import (personal_r, ExpenseIn, SleepIn, MoodIn, JournalIn,
                       log_mood_impl, log_sleep_impl, add_expense_impl, journal_entry_impl)
from .career import career_r
from .memory import memory_r, store_memory, search_memory
from .automations import auto_r
from .activity import activity_r
from .notifications import notes_r
from .push import push_r
from .approvals import approvals_r
from .missions import missions_r
from .kanban import board_r
from .workers import worker_r
from .consolidation import consol_r
from .gateway import gateway_r
from .briefings import brief_r
from .mail import mail_r
from .calendar import cal_r
from .sync import sync_r
from .proactive import pro_r
from .undo import undo_r
from .costs import cost_r
from .analytics import analytics_r
from .home import home_r

# All routers in mount order — matches original domain.py ROUTERS list
ROUTERS = [
    tasks_r, clients_r, projects_r, career_r, personal_r, memory_r, auto_r,
    activity_r, notes_r, approvals_r, gateway_r, push_r,
    brief_r, mail_r, cal_r, sync_r, pro_r, undo_r, cost_r, analytics_r,
    missions_r, home_r, consol_r, board_r, worker_r,
]
