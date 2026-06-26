import logging
from contextvars import ContextVar
from datetime import datetime

import pytz

_run_id: ContextVar[str] = ContextVar("run_id", default="-")

_MOROCCO_TZ = pytz.timezone("Africa/Casablanca")


def new_run_id() -> str:
    now = datetime.now(_MOROCCO_TZ)
    return f"run-{now:%H%M}"


def set_run_id(rid: str) -> None:
    _run_id.set(rid)


def get_run_id() -> str:
    return _run_id.get()


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id.get()
        return True
