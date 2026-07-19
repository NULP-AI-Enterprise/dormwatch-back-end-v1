from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings


class EmailDomainJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, validated_token = result
        email = validated_token.get('email', '')
        if not email:
            raise AuthenticationFailed('Token missing email claim')
        return (user, validated_token)
