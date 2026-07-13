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

from .models import UserProfile, DormitoryBuilding, Place, Role
from .serializers import RegisterSerializer, DormitoryBuildingSerializer, PlaceSerializer

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

        domain = email.split('@')[-1] if '@' in email else ''
        allowed = [d.strip().lower() for d in settings.ALLOWED_EMAIL_DOMAINS]
        if domain not in allowed:
            return Response(
                {'detail': f'Email domain @{domain} is not authorized'},
                status=status.HTTP_403_FORBIDDEN,
            )

        user = authenticate(request, username=email, password=password)
        if user is None:
            return Response(
                {'detail': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED,
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

            is_first_user = not UserProfile.objects.exists()

            if is_first_user:
                role, _ = Role.objects.get_or_create(role_name='admin')
                user.is_staff = True
                user.is_superuser = True
                user.save()
            else:
                role, _ = Role.objects.get_or_create(role_name='student')

            place = serializer.validated_data.get('place_id')
            building = serializer.validated_data.get('building_id')

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
        domain = email.split('@')[-1].lower() if '@' in email else ''
        allowed = [d.strip().lower() for d in settings.ALLOWED_EMAIL_DOMAINS]
        if domain not in allowed:
            return Response(
                {'detail': 'Domain not authorized'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

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
