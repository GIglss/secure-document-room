"""Verification email delivery via Azure Communication Services (optional).

If ACS_CONNECTION_STRING and ACS_SENDER_ADDRESS are both set, verification
codes are emailed for real and MUST NOT be surfaced in API responses.
Otherwise the join flow falls back to the dev mock (code printed / returned
in DEV_MODE).
"""
import os


def acs_email_configured() -> bool:
    return bool(os.getenv("ACS_CONNECTION_STRING", "").strip()) and bool(
        os.getenv("ACS_SENDER_ADDRESS", "").strip()
    )


def send_verification_email(to_email: str, code: str, room_name: str):
    """Send the 6-digit verification code via azure-communication-email.

    Raises on failure so the caller can surface a delivery error instead of
    leaving the recipient waiting for an email that never arrives.
    """
    from azure.communication.email import EmailClient

    connection_string = os.getenv("ACS_CONNECTION_STRING", "").strip()
    sender_address = os.getenv("ACS_SENDER_ADDRESS", "").strip()

    client = EmailClient.from_connection_string(connection_string)
    message = {
        "senderAddress": sender_address,
        "recipients": {"to": [{"address": to_email}]},
        "content": {
            "subject": f"Your verification code for \"{room_name}\"",
            "plainText": (
                f"Your verification code is: {code}\n\n"
                f"Enter this code to access the secure document room \"{room_name}\". "
                f"The code expires shortly and can only be used once.\n\n"
                f"If you did not request access, you can ignore this email."
            ),
            "html": (
                f"<p>Your verification code is:</p>"
                f"<p style=\"font-size:28px;font-weight:bold;letter-spacing:4px\">{code}</p>"
                f"<p>Enter this code to access the secure document room "
                f"<strong>{room_name}</strong>. The code expires shortly and can "
                f"only be used once.</p>"
                f"<p>If you did not request access, you can ignore this email.</p>"
            ),
        },
    }
    # begin_send performs the submit request synchronously; we don't block on
    # final delivery status (the poller), only on ACS accepting the message.
    client.begin_send(message)
