import random
import logging
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from .models import EmailVerificationCode, PasswordResetCode

logger = logging.getLogger(__name__)

def generate_code():
    return "".join([str(random.randint(0, 9)) for _ in range(6)])

def send_verification_email(user):
    code = generate_code()
    expires_at = timezone.now() + timedelta(minutes=15)
    
    # Invalidate older codes
    EmailVerificationCode.objects.filter(user=user, is_used=False).update(is_used=True)
    
    # Save new code
    EmailVerificationCode.objects.create(
        user=user,
        code=code,
        expires_at=expires_at
    )
    
    subject = "DormWatch - Email Verification Code"
    message = f"Hello,\n\nYour DormWatch email verification code is: {code}\n\nThis code expires in 15 minutes."
    
    # If not configured, print to logs/console for ease of development
    if not settings.EMAIL_HOST_USER:
        logger.info(f"--- DEVELOPMENT EMAIL VERIFICATION CODE FOR {user.email}: {code} ---")
        print(f"--- DEVELOPMENT EMAIL VERIFICATION CODE FOR {user.email}: {code} ---")
        return True

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send verification email to {user.email}: {e}")
        logger.info(f"--- FAILED TO SEND EMAIL. CODE WAS: {code} ---")
        raise e

def send_password_reset_email(user):
    code = generate_code()
    expires_at = timezone.now() + timedelta(minutes=15)
    
    # Invalidate older codes
    PasswordResetCode.objects.filter(user=user, is_used=False).update(is_used=True)
    
    # Save new code
    PasswordResetCode.objects.create(
        user=user,
        code=code,
        expires_at=expires_at
    )
    
    subject = "DormWatch - Password Reset Code"
    message = f"Hello,\n\nYour DormWatch password reset code is: {code}\n\nThis code expires in 15 minutes."
    
    if not settings.EMAIL_HOST_USER:
        logger.info(f"--- DEVELOPMENT PASSWORD RESET CODE FOR {user.email}: {code} ---")
        print(f"--- DEVELOPMENT PASSWORD RESET CODE FOR {user.email}: {code} ---")
        return True

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send password reset email to {user.email}: {e}")
        logger.info(f"--- FAILED TO SEND EMAIL. CODE WAS: {code} ---")
        raise e
