import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

from config import GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL

logger = logging.getLogger(__name__)


def _create_message(subject: str, html_body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def send_email(subject: str, html_body: str) -> None:
    msg = _create_message(subject, html_body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    logger.info(f"Email sent: {subject}")


def send_morning_briefing(html_body: str, health_html: str | None = None) -> None:
    if health_html:
        html_body = html_body.replace("</body>", f"{health_html}</body>")
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    send_email(f"BVC Morning Briefing — {date_str}", html_body)


def send_alert(html_body: str, ticker: str | None, alert_type: str) -> None:
    ticker_str = f" [{ticker}]" if ticker else ""
    send_email(f"BVC Alert{ticker_str}: {alert_type}", html_body)
