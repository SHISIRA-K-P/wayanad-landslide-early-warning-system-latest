# """Send one explicitly authorized test email using the project's Django settings."""

# import argparse
# import os
# import smtplib
# import sys
# from pathlib import Path


# APP_DIR = Path(__file__).resolve().parents[1]
# sys.path.insert(0, str(APP_DIR))
# os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"


# def main():
#     parser = argparse.ArgumentParser(
#         description="Send one test email using this project's Django SMTP settings."
#     )
#     parser.add_argument(
#         "recipient",
#         help="Email address for a test inbox that you control or may use.",
#     )
#     parser.add_argument(
#         "--send",
#         action="store_true",
#         help="Submit the test email. Required to prevent accidental sends.",
#     )
#     args = parser.parse_args()

#     import django

#     django.setup()

#     from django.conf import settings
#     from django.core.exceptions import ImproperlyConfigured, ValidationError
#     from django.core.mail import send_mail
#     from django.core.validators import validate_email

#     try:
#         validate_email(args.recipient)
#     except ValidationError:
#         parser.error("recipient must be a valid email address.")

#     if not args.send:
#         parser.error(
#             "No email sent. Add --send to submit one message to this test recipient."
#         )

#     required_settings = {
#         "EMAIL_BACKEND": settings.EMAIL_BACKEND,
#         "EMAIL_HOST": settings.EMAIL_HOST,
#         "EMAIL_HOST_USER": settings.EMAIL_HOST_USER,
#         "EMAIL_HOST_PASSWORD": settings.EMAIL_HOST_PASSWORD,
#         "DEFAULT_FROM_EMAIL": settings.DEFAULT_FROM_EMAIL,
#     }
#     missing = [name for name, value in required_settings.items() if not value]
#     if missing:
#         print(
#             "Email failed: missing Django settings: " + ", ".join(missing),
#             file=sys.stderr,
#         )
#         return 1

#     if (
#         settings.EMAIL_BACKEND
#         != "django.core.mail.backends.smtp.EmailBackend"
#     ):
#         print(
#             "Email failed: EMAIL_BACKEND is not Django's SMTP backend.",
#             file=sys.stderr,
#         )
#         return 1

#     if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
#         print(
#             "Email failed: EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be true.",
#             file=sys.stderr,
#         )
#         return 1

#     try:
#         sent_count = send_mail(
#             subject="Wayanad project SMTP test",
#             message=(
#                 "This is an authorized SMTP configuration test from the "
#                 "Wayanad learning prototype. It is not an emergency alert."
#             ),
#             from_email=settings.DEFAULT_FROM_EMAIL,
#             recipient_list=[args.recipient],
#             fail_silently=False,
#         )
#     except (smtplib.SMTPException, OSError, ImproperlyConfigured) as exc:
#         print(
#             f"Email failed: {type(exc).__name__}: {exc}",
#             file=sys.stderr,
#         )
#         return 1

#     if sent_count != 1:
#         print(
#             f"Email not confirmed: Django reported {sent_count} messages sent.",
#             file=sys.stderr,
#         )
#         return 1

#     print(
#         f"Django's email backend accepted one test message for {args.recipient}."
#     )
#     print("Check the recipient inbox and spam folder for delivery.")
#     return 0


# if __name__ == "__main__":
#     raise SystemExit(main())

# Gmail SMTP Configuration

# # EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# EMAIL_HOST = "smtp.gmail.com"
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True

# EMAIL_HOST_USER = "shisirahasvika@gmail.com"
# EMAIL_HOST_PASSWORD = "pmvu btuz jcay yjkl"

# DEFAULT_FROM_EMAIL = EMAIL_HOST_USER


import smtplib
from email.message import EmailMessage

# Email configuration
sender_email = ""
app_password = ""
receiver_email = ""

# Create email
msg = EmailMessage()
msg["Subject"] = "Test Email"
msg["From"] = sender_email
msg["To"] = receiver_email
msg.set_content("Hello! Your Python email setup is working correctly.")

try:
    print("Connecting to Gmail...")

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender_email, app_password)
        server.send_message(msg)

    print("SUCCESS: Email sent successfully!")

except Exception as e:
    print("FAILED: Email could not be sent.")
    print("Error:", e)