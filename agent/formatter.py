from pathlib import Path
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).parent.parent / "delivery" / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))


def format_morning_briefing(analysis: dict, date: str) -> str:
    template = _env.get_template("morning_briefing.html")
    return template.render(date=date, **analysis)


def format_alert(analysis: dict) -> str:
    template = _env.get_template("alert.html")
    return template.render(**analysis)
