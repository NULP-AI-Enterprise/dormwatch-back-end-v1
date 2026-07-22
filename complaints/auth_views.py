import logging

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


from django.utils import timezone
from .models import UserProfile, DormitoryBuilding, Place, Role, InviteToken, EmailVerificationCode, PasswordResetCode
from .serializers import RegisterSerializer, DormitoryBuildingSerializer, PlaceSerializer
from .email_utils import send_verification_email, send_password_reset_email

logger = logging.getLogger(__name__)


def _get_tokens_for_user(user):
    token = RefreshToken.for_user(user)
    token['email'] = user.email
    return {
        'access': str(token.access_token),
        'refresh': str(token),
    }


def _set_refresh_cookie(response, refresh_token):
    secure = not settings.DEBUG
    response.set_cookie(
        key='refresh_token',
        value=refresh_token,
        max_age=7 * 24 * 3600,
        httponly=True,
        secure=secure,
        samesite='Lax',
        path='/api/auth',
    )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        if not email or not password:
            return Response(
                {'detail': 'Email and password are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=email, password=password)
        if user is None:
            return Response(
                {'detail': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Check verification
        profile = getattr(user, 'profile', None)
        if not profile or not profile.is_email_verified:
            try:
                send_verification_email(user)
            except Exception as e:
                logger.error(f"Failed to send verification email on login: {e}")
            return Response(
                {
                    'detail': 'Email verification required. A verification code has been sent to your email.',
                    'email_verified': False,
                    'email': user.email
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        tokens = _get_tokens_for_user(user)
        response = Response({'access': tokens['access']}, status=status.HTTP_200_OK)
        _set_refresh_cookie(response, tokens['refresh'])
        return response


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            user = serializer.save()

            invite_token = serializer.validated_data.get('invite_token')
            invite = None
            if invite_token:
                try:
                    invite = InviteToken.objects.get(token=invite_token, is_used=False)
                except InviteToken.DoesNotExist:
                    # Token was already validated in serializer, but just in case
                    pass

            is_first_user = not UserProfile.objects.exists()

            if is_first_user:
                role, _ = Role.objects.get_or_create(role_name='admin')
                user.is_staff = True
                user.is_superuser = True
                user.save()
            elif invite:
                role = invite.role
                if role.role_name == 'admin':
                    user.is_staff = True
                    user.is_superuser = True
                    user.save()
                invite.is_used = True
                invite.save()
            else:
                role, _ = Role.objects.get_or_create(role_name='student')

            place = serializer.validated_data.get('place_id')
            building = serializer.validated_data.get('building_id')

            if invite:
                if invite.building_id:
                    building = invite.building_id
                if invite.place_id:
                    place = invite.place_id

            # Building is a first-class profile field, independent of room, so a
            # user can register with a building but no room yet. If a room was
            # chosen without an explicit building, keep them consistent by
            # deriving the building from the room.
            if not building and place:
                building = (
                    Place.objects.filter(place_id=place)
                    .values_list('building_id', flat=True)
                    .first()
                )

            UserProfile.objects.create(
                user=user,
                first_name=serializer.validated_data.get('first_name', ''),
                last_name=serializer.validated_data.get('last_name', ''),
                email=user.email,
                role=role,
                place_id=place,
                building_id=building,
                is_email_verified=is_first_user,  # auto-verify the first bootstrap admin
            )

        if not is_first_user:
            try:
                send_verification_email(user)
            except Exception as e:
                logger.error(f"Failed to send registration verification email: {e}")
            return Response(
                {
                    'detail': 'Registration successful. A verification code has been sent to your email.',
                    'email_verified': False,
                    'email': user.email
                },
                status=status.HTTP_201_CREATED,
            )

        tokens = _get_tokens_for_user(user)
        response = Response(
            {'access': tokens['access'], 'detail': 'Registration successful'},
            status=status.HTTP_201_CREATED,
        )
        _set_refresh_cookie(response, tokens['refresh'])
        return response


class CookieTokenRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.COOKIES.get('refresh_token')
        if not refresh_token:
            return Response(
                {'detail': 'No refresh token'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Parse + verify the incoming token. A TokenError here means the token
        # is expired, malformed, or already blacklisted (rotation replay) —
        # distinguish these for diagnosis but all end in a 401.
        try:
            old = RefreshToken(refresh_token)
        except TokenError as exc:
            # "Token is blacklisted" / "expired" / signature errors all surface
            # here. Surface the cause so a replayed (already-rotated) token is
            # distinguishable from a genuinely expired one in the logs.
            detail = str(exc)
            logger.info('Refresh rejected: %s', detail)
            return Response(
                {'detail': f'Invalid or expired refresh token: {detail}'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        email = old.payload.get('email', '')

        # Resolve the user from the verified token's user_id claim.
        user_id = old.payload.get('user_id')
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                {'detail': 'User no longer exists'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Rotate: blacklist the presented token's jti (BLACKLIST_AFTER_ROTATION)
        # then mint a brand-new refresh token with a fresh jti. The new token
        # must re-carry the email claim or EmailDomainJWTAuthentication rejects
        # the access tokens it mints.
        try:
            old.blacklist()
        except TokenError as exc:
            # Race: token blacklisted between verify and here — treat as replay.
            logger.info('Refresh rotation blacklist race: %s', exc)
            return Response(
                {'detail': 'Refresh token already used'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        new = RefreshToken.for_user(user)
        new['email'] = user.email

        response = Response(
            {'access': str(new.access_token)},
            status=status.HTTP_200_OK,
        )
        _set_refresh_cookie(response, str(new))
        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        # Blacklist the refresh token so the session is actually invalidated
        # server-side, then clear the cookie. A missing/invalid token still
        # results in a successful logout (nothing to invalidate).
        refresh_token = request.COOKIES.get('refresh_token')
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError as exc:
                logger.info('Logout with unusable refresh token: %s', exc)

        response = Response(
            {'detail': 'Logged out'},
            status=status.HTTP_200_OK,
        )
        response.delete_cookie('refresh_token', path='/api/auth')
        return response


class BuildingListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        buildings = DormitoryBuilding.objects.all().order_by('name')
        serializer = DormitoryBuildingSerializer(buildings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PlaceListView(APIView):
    # AllowAny for GET (register/report pickers), IsAuthenticated for POST
    # (creating a room requires a logged-in user).
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request):
        building_id = request.query_params.get('building_id')
        if not building_id:
            return Response(
                {'detail': 'building_id query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        places = Place.objects.filter(
            building_id=building_id
        ).order_by('place_name')
        serializer = PlaceSerializer(places, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        building_id = request.data.get('building_id')
        place_name = (request.data.get('place_name') or '').strip()
        if not building_id or not place_name:
            return Response(
                {'detail': 'building_id and place_name are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            building = DormitoryBuilding.objects.get(building_id=building_id)
        except DormitoryBuilding.DoesNotExist:
            return Response(
                {'detail': 'Building not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        place, _ = Place.objects.get_or_create(
            building=building, place_name=place_name
        )
        # capacity / is_shared are optional; apply them when provided so the
        # same endpoint can create a residence (capacity>0) or a shared room.
        dirty = False
        if 'capacity' in request.data:
            place.capacity = request.data.get('capacity') or 0
            dirty = True
        if 'is_shared' in request.data:
            place.is_shared = bool(request.data.get('is_shared'))
            dirty = True
        if dirty:
            place.save()
        serializer = PlaceSerializer(place)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class InviteTokenCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if getattr(request.user, 'is_staff', False) is not True:
            return Response({'detail': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
            
        role_id = request.data.get('role_id')
        building_id = request.data.get('building_id')
        place_id = request.data.get('place_id')
        
        if not role_id:
            return Response({'detail': 'role_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            role = Role.objects.get(role_id=role_id)
        except Role.DoesNotExist:
            return Response({'detail': 'Role not found'}, status=status.HTTP_404_NOT_FOUND)
            
        token = InviteToken.objects.create(
            role=role,
            building_id=building_id,
            place_id=place_id,
            created_by=request.user
        )
        
        return Response({'invite_token': str(token.token)}, status=status.HTTP_201_CREATED)
      

class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        code = request.data.get('code', '').strip()

        if not email or not code:
            return Response(
                {'detail': 'Email and code are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {'detail': 'Invalid email or code'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        verification = EmailVerificationCode.objects.filter(
            user=user,
            code=code,
            is_used=False,
            expires_at__gt=now
        ).first()

        if not verification:
            return Response(
                {'detail': 'Invalid or expired verification code'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        verification.is_used = True
        verification.save()

        profile = getattr(user, 'profile', None)
        if profile:
            profile.is_email_verified = True
            profile.save()

        tokens = _get_tokens_for_user(user)
        response = Response(
            {'access': tokens['access'], 'detail': 'Email verified successfully'},
            status=status.HTTP_200_OK,
        )
        _set_refresh_cookie(response, tokens['refresh'])
        return response


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response(
                {'detail': 'Email is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)
            send_password_reset_email(user)
        except User.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Error in PasswordResetRequestView: {e}")
            return Response(
                {'detail': 'Failed to send password reset email. Please try again later.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {'detail': 'If the email is registered, a password reset code has been sent.'},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        code = request.data.get('code', '').strip()
        password = request.data.get('password', '')
        confirm_password = request.data.get('confirm_password', '')

        if not email or not code or not password or not confirm_password:
            return Response(
                {'detail': 'All fields (email, code, password, confirm_password) are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if password != confirm_password:
            return Response(
                {'detail': 'Passwords do not match'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(password) < 8:
            return Response(
                {'detail': 'Password must be at least 8 characters long'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {'detail': 'Invalid email or code'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        reset_code = PasswordResetCode.objects.filter(
            user=user,
            code=code,
            is_used=False,
            expires_at__gt=now
        ).first()

        if not reset_code:
            return Response(
                {'detail': 'Invalid or expired password reset code'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reset_code.is_used = True
        reset_code.save()

        user.set_password(password)
        user.save()

        profile = getattr(user, 'profile', None)
        if profile and not profile.is_email_verified:
            profile.is_email_verified = True
            profile.save()

        return Response(
            {'detail': 'Password has been reset successfully'},
            status=status.HTTP_200_OK,
        )


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        old_password = request.data.get('old_password', '')
        new_password = request.data.get('new_password', '')
        confirm_new_password = request.data.get('confirm_new_password', '')

        if not old_password or not new_password or not confirm_new_password:
            return Response(
                {'detail': 'All fields (old_password, new_password, confirm_new_password) are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != confirm_new_password:
            return Response(
                {'detail': 'New passwords do not match'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 8:
            return Response(
                {'detail': 'Password must be at least 8 characters long'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        if not user.check_password(old_password):
            return Response(
                {'detail': 'Incorrect old password'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save()

        return Response(
            {'detail': 'Password changed successfully'},
            status=status.HTTP_200_OK,
        )
