import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
APP_URL   = os.environ.get("APP_URL", "http://localhost:5050")


def send_password_reset(to_email: str, username: str, token: str) -> bool:
    if not SMTP_USER or not SMTP_PASS:
        return False

    reset_url = f"{APP_URL}/reset-password/{token}"

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;background:#fff;border-radius:16px;">
      <h2 style="font-size:22px;font-weight:700;color:#1a1a1a;margin:0 0 8px;">Reset your password</h2>
      <p style="color:#555;font-size:15px;line-height:1.5;margin:0 0 24px;">
        Hi {username}, we received a request to reset your CalDef password.
        Click the button below — this link expires in <strong>1 hour</strong>.
      </p>
      <a href="{reset_url}"
         style="display:inline-block;background:#007AFF;color:#fff;text-decoration:none;
                font-size:15px;font-weight:600;padding:14px 28px;border-radius:12px;">
        Reset Password
      </a>
      <p style="color:#999;font-size:13px;margin:24px 0 0;">
        If you didn't request this, you can safely ignore this email.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset your CalDef password"
    msg["From"]    = f"CalDef <{SMTP_USER}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        return True
    except Exception:
        return False
