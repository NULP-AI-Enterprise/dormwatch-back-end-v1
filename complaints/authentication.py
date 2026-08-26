from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings


class EmailDomainJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, validated_token = result
        
        from complaints.models import UserProfile
        user_profile = UserProfile.objects.filter(user=user).first()
        is_student = user_profile and user_profile.role and user_profile.role.role_name.lower() in ['student', 'студент']

        if is_student:
            email = validated_token.get('email', '')
            if not email:
                raise AuthenticationFailed('Token missing email claim')
            domain = email.split('@')[-1].lower() if '@' in email else ''
            if domain not in settings.ALLOWED_EMAIL_DOMAINS:
                raise AuthenticationFailed(
                    f'Email domain @{domain} is not authorized for student accounts'
                )
        return (user, validated_token)
