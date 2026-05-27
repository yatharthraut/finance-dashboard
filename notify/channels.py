"""Send a text via the channel configured in .env (NOTIFY_CHANNEL).

Channels (all stdlib — no extra dependencies):
  * email_sms — SMTP -> carrier email-to-SMS gateway (free)
  * twilio    — Twilio REST API (paid, reliable)
  * ntfy      — ntfy.sh push notification (free, easiest; not true SMS)
  * console   — just print (default; for testing)
"""

from __future__ import annotations

import base64
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage

import utils.config  # noqa: F401  (importing loads .env into the environment)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def send(text: str, subject: str = "Spending update") -> str:
    """Dispatch to the configured channel. Returns a human-readable status."""
    channel = _env("NOTIFY_CHANNEL", "console").lower()
    if channel == "email_sms":
        return _send_email_sms(text, subject)
    if channel == "twilio":
        return _send_twilio(text)
    if channel == "ntfy":
        return _send_ntfy(text, subject)
    print(text)
    return "printed to console (set NOTIFY_CHANNEL to actually send)"


def _send_email_sms(text: str, subject: str) -> str:
    host = _env("SMTP_HOST", "smtp.gmail.com")
    port = int(_env("SMTP_PORT", "587"))
    user = _env("SMTP_USER")
    password = _env("SMTP_PASS")
    to = _env("SMS_TO_EMAIL")  # e.g. 5551234567@vtext.com
    if not (user and password and to):
        raise RuntimeError("email_sms needs SMTP_USER, SMTP_PASS, SMS_TO_EMAIL in .env")

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(user, password)
        server.send_message(msg)
    return f"sent via email-to-SMS gateway to {to}"


def _send_twilio(text: str) -> str:
    sid = _env("TWILIO_ACCOUNT_SID")
    token = _env("TWILIO_AUTH_TOKEN")
    from_ = _env("TWILIO_FROM")
    to = _env("SMS_TO")
    if not all([sid, token, from_, to]):
        raise RuntimeError(
            "twilio needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, SMS_TO"
        )
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = urllib.parse.urlencode({"From": from_, "To": to, "Body": text}).encode()
    req = urllib.request.Request(url, data=data)
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return f"twilio HTTP {resp.status}"


def _send_ntfy(text: str, subject: str) -> str:
    server = _env("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    topic = _env("NTFY_TOPIC")
    if not topic:
        raise RuntimeError("ntfy needs NTFY_TOPIC in .env")
    req = urllib.request.Request(f"{server}/{topic}", data=text.encode("utf-8"))
    req.add_header("Title", subject)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return f"ntfy HTTP {resp.status}"
