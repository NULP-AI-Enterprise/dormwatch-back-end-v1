from decimal import Decimal
from django.contrib.auth.models import User
from django.conf import settings
from rest_framework import serializers
from .models import Complaint, UserProfile, Comment, DormitoryBuilding, Place, ComplaintCategory, Role, Notification, Worker, Announcement, ComplaintEvent, InviteToken, COMPLAINT_STATUS, COMPLAINT_PRIORITY, Resource, ComplaintResource
from .image_utils import process_complaint_photo


def _validate_assignable_place(place, exclude_profile_pk=None):
    """Reject assigning a resident to a room that isn't a valid residence.

    A place is unassignable if it is shared (kitchen/laundry/common — a complaint
    location only) or is a private room already at/over capacity. `capacity == 0`
    means "not configured as a residence", so it is never assignable — an admin
    must set a real capacity first. `exclude_profile_pk` drops the profile being
    edited from the occupancy count so re-saving a resident already in the room
    (or just changing their role) does not falsely trip the block.

    Raises serializers.ValidationError({'place_id': ...}) в†’ HTTP 400.
    """
    if place is None:
        return
    if place.is_shared:
        raise serializers.ValidationError(
            {'place_id': 'Кімната є спільною і не може бути житловою'}
        )
    occupancy = UserProfile.objects.filter(place=place)
    if exclude_profile_pk is not None:
        occupancy = occupancy.exclude(pk=exclude_profile_pk)
    if place.capacity == 0 or occupancy.count() >= place.capacity:
        raise serializers.ValidationError(
            {'place_id': 'Кімната переповнена або не є житловою'}
        )


class DormitoryBuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model = DormitoryBuilding
        fields = ("building_id", "name", "address", "commandant_phone")


class PlaceSerializer(serializers.ModelSerializer):
    building = DormitoryBuildingSerializer()
    # Live count of residents assigned to this room (UserProfile.place FK).
    occupancy = serializers.SerializerMethodField()

    class Meta:
        model = Place
        fields = ("place_id", "place_name", "building", "capacity", "is_shared", "occupancy")

    def get_occupancy(self, obj):
        return UserProfile.objects.filter(place=obj).count()


class PlaceWriteSerializer(serializers.ModelSerializer):
    building_id = serializers.PrimaryKeyRelatedField(
        source='building', queryset=DormitoryBuilding.objects.all()
    )

    class Meta:
        model = Place
        fields = ("place_id", "place_name", "building_id", "capacity", "is_shared")


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ("role_id", "role_name")


class UserSerializer(serializers.ModelSerializer):
    is_staff = serializers.BooleanField(source="user.is_staff", read_only=True)
    place = PlaceSerializer(read_only=True)
    building = DormitoryBuildingSerializer(read_only=True)
    role = RoleSerializer(read_only=True)
    class Meta:
        model = UserProfile
        fields = ['user', 'first_name', 'last_name', 'email', 'place', 'building', 'photo_url', 'role', 'phone', 'is_staff']


class UpdateUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['first_name', 'last_name', 'email', 'photo_url', 'phone']


class UpdateUserPlaceSerializer(serializers.Serializer):
    place_id = serializers.IntegerField()


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplaintCategory
        fields = ['category_id', 'name']


class UserComplaintSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['user', 'first_name', 'last_name', 'photo_url']


class WorkerSerializer(serializers.ModelSerializer):
    has_account = serializers.SerializerMethodField()

    class Meta:
        model = Worker
        fields = ['worker_id', 'full_name', 'company', 'phone', 'has_account']

    def get_has_account(self, obj):
        return obj.account_id is not None

class ComplaintEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = ComplaintEvent
        fields = ['event_id', 'action', 'actor', 'actor_name', 'created_at']

    def get_actor_name(self, obj):
        if obj.actor is None:
            return None
        return f"{obj.actor.first_name} {obj.actor.last_name}".strip() or None


def _get_student_phone_if_allowed(obj, request):
    if not request or not request.user.is_authenticated:
        return None
    user = request.user
    profile = getattr(user, 'profile', None)
    is_admin = user.is_staff or user.is_superuser or bool(
        profile and profile.role and profile.role.role_name.lower() in ['admin', 'адміністратор']
    )
    if is_admin:
        return None
    is_worker = bool(
        profile and profile.role and profile.role.role_name.lower() in ['worker', 'працівник']
    )
    is_owner = (obj.user_id == user.id)
    if (is_owner or is_worker) and obj.user and obj.user.phone:
        return obj.user.phone
    return None


# Public board serializer: rooms/photos and the author identity are hidden
# from everyone but staff — the feed shows what happened, never who/where
# exactly lives behind it.
class PublicComplaintSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='complaint_id', read_only=True)
    category = CategorySerializer(read_only=True)
    building_name = serializers.SerializerMethodField()
    supporters_count = serializers.SerializerMethodField()
    is_shared = serializers.SerializerMethodField()
    place_name = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()
    user_id = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    place_id = serializers.IntegerField(source='place.place_id', read_only=True, allow_null=True)
    photo_url = serializers.ImageField(read_only=True)
    thumbnail = serializers.ImageField(read_only=True)
    student_phone = serializers.SerializerMethodField()

    class Meta:
        model = Complaint
        fields = ['id', 'complaint_id', 'title', 'description', 'category', 'status',
                  'priority', 'created_at', 'building_name', 'supporters_count',
                  'is_shared', 'place_name', 'place_id', 'is_mine', 'user_id', 'user_name',
                  'photo_url', 'thumbnail', 'is_rework', 'student_phone']

    def get_student_phone(self, obj):
        request = self.context.get('request')
        return _get_student_phone_if_allowed(obj, request)

    def get_building_name(self, obj):
        place = obj.place
        return place.building.name if place and place.building else None

    def get_supporters_count(self, obj):
        return obj.supporters.count()

    def get_is_shared(self, obj):
        return obj.place.is_shared if obj.place else False

    def get_place_name(self, obj):
        if obj.place and (obj.place.is_shared or '[Блок]' in (obj.description or '')):
            return obj.place.place_name
        return None

    def get_is_mine(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.user_id == request.user.id
        return False

    def get_user_id(self, obj):
        return obj.user.user_id if obj.user else None

    def get_user_name(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            user = request.user
            if obj.user_id == user.id:
                return f"{obj.user.first_name} {obj.user.last_name}".strip() if obj.user else ""
            profile = getattr(user, 'profile', None)
            if profile and profile.role and profile.role.role_name.lower() in ['admin', 'адміністратор']:
                return f"{obj.user.first_name} {obj.user.last_name}".strip() if obj.user else ""
        return "Автор звернення"


# Owner/admin read shape: full lifecycle + assignment + re-file chain links.
class ComplaintSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='complaint_id', read_only=True)
    category = CategorySerializer(read_only=True)
    place = PlaceSerializer(read_only=True)
    user = UserComplaintSerializer(read_only=True)
    worker = WorkerSerializer(read_only=True)
    # Derived, never stored: the views.annotate_is_overdue annotation
    # (`overdue_flag`) when present (lists), the model property otherwise
    # (single objects).
    is_overdue = serializers.SerializerMethodField()
    supporters_count = serializers.SerializerMethodField()
    student_phone = serializers.SerializerMethodField()

    class Meta:
        model = Complaint
        fields = [
            'id', 'complaint_id', 'user', 'title', 'description', 'category', 'status',
            'photo_url', 'thumbnail', 'created_at', 'place', 'priority',
            'resolved_at',
            'worker', 'deadline', 'started_at', 'finished_at', 'work_note',
            'rejection_reason', 'rework_reason', 'is_rework', 'rework_photo', 'completion_photo',
            'follow_up_of', 'root', 'is_overdue', 'supporters_count', 'student_phone',
        ]
        read_only_fields = ['id', 'complaint_id', 'created_at', 'user', 'status']

    def get_student_phone(self, obj):
        request = self.context.get('request')
        return _get_student_phone_if_allowed(obj, request)

    def get_is_overdue(self, obj):
        flagged = getattr(obj, 'overdue_flag', None)
        if flagged is not None:
            return flagged
        return bool(obj.is_overdue)

    def get_supporters_count(self, obj):
        return obj.supporters.count()


# Resident create whitelist: a resident payload has no status/priority/worker.
class ComplaintCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = ['title', 'description', 'photo_url']

    def create(self, validated_data):
        uploaded_file = validated_data.pop('photo_url', None)
        if uploaded_file:
            result = process_complaint_photo(uploaded_file)
            validated_data['photo_url'] = result['full']
            validated_data['thumbnail'] = result['thumbnail']
        return super().create(validated_data)


# Admin detail: everything above plus soft-delete bookkeeping, the event log,
# and the follow-up chain children.
class AdminComplaintDetailSerializer(ComplaintSerializer):
    events = ComplaintEventSerializer(many=True, read_only=True)

    class Meta(ComplaintSerializer.Meta):
        fields = ComplaintSerializer.Meta.fields + [
            'archived', 'archived_by', 'archived_at', 'events',
        ]


# Admin PATCH whitelist. The allowed-field list IS the rule: assignment,
# deadline, triage status moves, rejection reason, priority. Anything else a
# client sends here is ignored, and other endpoints simply don't accept these
# fields for their roles.
class AdminComplaintUpdateSerializer(serializers.Serializer):
    worker_id = serializers.IntegerField(required=False, allow_null=True)
    deadline = serializers.DateTimeField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=[s for s, _ in COMPLAINT_STATUS], required=False)
    rejection_reason = serializers.CharField(required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=[p for p, _ in COMPLAINT_PRIORITY], required=False)


# Worker-scoped read: job context only (what to fix, where, by when). No
# resident identity, no dorm-wide fields. Chain links + created_at let the
# panel cite "Повторне до №N" and order a saga; stamps power the history.
class WorkerComplaintSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='complaint_id', read_only=True)
    category = CategorySerializer(read_only=True)
    place = PlaceSerializer(read_only=True)
    is_overdue = serializers.SerializerMethodField()
    student_phone = serializers.SerializerMethodField()
    assigned_at = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()
    latest_foreign_comment_id = serializers.SerializerMethodField()

    class Meta:
        model = Complaint
        fields = ['id', 'complaint_id', 'title', 'description', 'category', 'status',
                  'priority', 'place', 'photo_url', 'thumbnail',
                  'deadline', 'started_at', 'finished_at', 'work_note',
                  'is_rework', 'rework_reason', 'rework_photo', 'completion_photo',
                  'is_overdue', 'follow_up_of', 'root', 'created_at', 'student_phone',
                  'assigned_at', 'comments_count', 'latest_foreign_comment_id']

    def get_student_phone(self, obj):
        if obj.user and obj.user.phone:
            return obj.user.phone
        return None

    def get_is_overdue(self, obj):
        flagged = getattr(obj, 'overdue_flag', None)
        if flagged is not None:
            return flagged
        return bool(obj.is_overdue)

    def get_assigned_at(self, obj):
        ev = (
            obj.events
            .filter(action__in=['assigned', 'reassigned'])
            .order_by('-created_at', '-event_id')
            .first()
        )
        if ev:
            return ev.created_at
        return obj.started_at or obj.created_at

    def get_comments_count(self, obj):
        return obj.comment_set.count()

    def get_latest_foreign_comment_id(self, obj):
        request = self.context.get('request')
        qs = obj.comment_set.all()
        if request and request.user.is_authenticated:
            qs = qs.exclude(user_id=request.user.id)
        latest = qs.order_by('-comment_id').first()
        return latest.comment_id if latest else None


# Worker PATCH whitelist: stamps via explicit action verbs + optional note and completion photo.
class WorkerStampSerializer(serializers.Serializer):
    ACTION_CHOICES = [
        ('start', 'Взято в роботу'),
        ('finish', 'Виконано'),
        ('start_undo', 'Скасовано початок робіт'),
        ('finish_undo', 'Скасовано виконання'),
    ]
    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    note = serializers.CharField(required=False, allow_blank=True)
    completion_photo = serializers.ImageField(required=False, allow_null=True)


class UpdateUserRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['role']


class AdminUpdateUserSerializer(serializers.ModelSerializer):
    # Admin write surface for a resident's dorm assignment + role. All three are
    # optional so a PATCH can touch any subset; nullable so a value can be
    # cleared (e.g. unassign a room). `*_id` mirrors the PlaceWriteSerializer
    # idiom above.
    role_id = serializers.PrimaryKeyRelatedField(
        source='role', queryset=Role.objects.all(),
        required=False, allow_null=True,
    )
    building_id = serializers.PrimaryKeyRelatedField(
        source='building', queryset=DormitoryBuilding.objects.all(),
        required=False, allow_null=True,
    )
    place_id = serializers.PrimaryKeyRelatedField(
        source='place', queryset=Place.objects.all(),
        required=False, allow_null=True,
    )

    class Meta:
        model = UserProfile
        fields = ['role_id', 'building_id', 'place_id']

    def validate(self, data):
        # `place_id` has source='place', so a provided value arrives as `place`
        # (a Place instance or None). Only enforce when a room is actually being
        # set; clearing it (None) is always allowed. Exclude the profile being
        # edited so re-saving a resident already in a full room stays valid.
        if 'place' in data and data['place'] is not None:
            _validate_assignable_place(
                data['place'],
                exclude_profile_pk=self.instance.pk if self.instance else None,
            )
        return data


class CommentSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    author_is_admin = serializers.SerializerMethodField()
    author_role = serializers.SerializerMethodField()
    class Meta:
        model = Comment
        fields = ['comment_id','complaint','user','user_name', 'author_is_admin', 'author_role', 'description', 'created_at']
        read_only_fields = ("created_at", "user",'complaint')

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()

    def get_author_is_admin(self, obj):
        return bool(obj.user.role and obj.user.role.role_name.lower() in ['admin', 'адміністратор'])

    def get_author_role(self, obj):
        if not obj.user.role:
            return 'student'
        r = (obj.user.role.role_name or '').lower()
        if r in ['admin', 'адміністратор']:
            return 'admin'
        if r in ['worker', 'працівник']:
            return 'worker'
        return 'student'


ALLOWED_INVITE_EMAIL_DOMAINS = {
    'lpnu.ua',
    'gmail.com',
    'ukr.net',
    'yahoo.com',
    'outlook.com',
    'hotmail.com',
    'icloud.com',
    'meta.ua',
    'i.ua',
    'email.ua',
    'proton.me',
    'protonmail.com',
    'live.com',
    'msn.com',
    'me.com',
    'mac.com',
}


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    place_id = serializers.IntegerField(required=False, allow_null=True)
    building_id = serializers.IntegerField(required=False, allow_null=True)
    invite_token = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def _get_invite(self, token):
        """The valid, unused InviteToken for `token`, or None."""
        if not token:
            return None
        import uuid
        try:
            uuid_obj = uuid.UUID(str(token).strip())
        except (ValueError, TypeError, AttributeError):
            return None
        return InviteToken.objects.filter(token=uuid_obj, is_used=False).first()

    def validate_email(self, value):
        email = value.strip().lower()
        domain = email.split('@')[-1] if '@' in email else ''
        allowed = [d.strip().lower() for d in settings.ALLOWED_EMAIL_DOMAINS]
        invite_token = self.initial_data.get('invite_token')

        invite = self._get_invite(invite_token)
        if invite_token and not invite:
            raise serializers.ValidationError('Недійсне або вже використане посилання-запрошення')

        if invite:
            is_valid_domain = domain in ALLOWED_INVITE_EMAIL_DOMAINS or domain.endswith('.lpnu.ua')
            if not is_valid_domain:
                raise serializers.ValidationError(
                    f'Поштовий домен @{domain} не підтримується. Перевірте правильність написання (наприклад, @gmail.com, @ukr.net, @lpnu.ua).'
                )
        else:
            if domain not in allowed and not domain.endswith('.lpnu.ua'):
                raise serializers.ValidationError(
                    f'Email domain @{domain} is not authorized'
                )

        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError('A user with this email already exists')
        return email

    def validate(self, data):
        if data.get('password') != data.get('confirm_password'):
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match'})
        # Building is required once any building exists. On an empty DB (first
        # user / admin bootstrap) there is nothing to pick, so it stays optional.
        # Any invite (admin or worker) is exempt from picking a resident building.
        building_id = data.get('building_id')
        if DormitoryBuilding.objects.exists() and not building_id:
            invite = self._get_invite(data.get('invite_token') or self.initial_data.get('invite_token'))
            if not invite:
                raise serializers.ValidationError({'building_id': 'Оберіть гуртожиток'})
        if building_id and not DormitoryBuilding.objects.filter(building_id=building_id).exists():
            raise serializers.ValidationError({'building_id': 'Building not found'})
        # A new user has no existing profile, so occupancy is the raw count.
        # Same rule as admin assignment: shared/full/capacity-0 rooms are rejected.
        place_id = data.get('place_id')
        if place_id:
            place = Place.objects.filter(place_id=place_id).first()
            if place is None:
                raise serializers.ValidationError({'place_id': 'Room not found'})
            _validate_assignable_place(place)
        return data

    def create(self, validated_data):
        email = validated_data['email']
        password = validated_data['password']
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        return user


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['notification_id', 'user', 'title', 'message', 'complaint', 'is_read', 'created_at']


class AnnouncementSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source='building.name', read_only=True, default=None)
    created_by_name = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = ['announcement_id', 'title', 'body', 'building', 'building_name',
                  'is_pinned', 'expires_at', 'is_expired',
                  'created_by', 'created_by_name', 'created_at']
        read_only_fields = ['created_by', 'created_at']

    def get_created_by_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.first_name} {obj.created_by.last_name}".strip() or None
        return None

    def get_is_expired(self, obj):
        from django.utils import timezone
        return bool(obj.expires_at and obj.expires_at < timezone.localdate())


class ResourceSerializer(serializers.ModelSerializer):
    unit_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False,
        error_messages={
            "invalid": "Введіть коректну ціну.",
            "min_value": "Ціна не може бути від’ємною.",
            "max_digits": "Ціна не може перевищувати 99 999 999,99 ₴ і мати більше 2 знаків після коми.",
            "max_whole_digits": "Ціна не може перевищувати 99 999 999,99 ₴.",
            "max_decimal_places": "Ціна може мати не більше 2 знаків після коми.",
        },
    )

    class Meta:
        model = Resource
        fields = ['resource_id', 'name', 'unit', 'unit_cost', 'description', 'created_at']
        read_only_fields = ['resource_id', 'created_at']


class ComplaintResourceSerializer(serializers.ModelSerializer):
    resource_details = ResourceSerializer(source='resource', read_only=True)
    logged_by_name = serializers.SerializerMethodField()
    total_cost = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)

    class Meta:
        model = ComplaintResource
        fields = [
            'id', 'complaint', 'resource', 'resource_details',
            'quantity', 'unit_cost', 'total_cost', 'notes',
            'logged_by', 'logged_by_name', 'created_at'
        ]
        read_only_fields = ['id', 'logged_by', 'created_at', 'total_cost']

    def get_logged_by_name(self, obj):
        if obj.logged_by:
            return f"{obj.logged_by.first_name} {obj.logged_by.last_name}".strip()
        return "Система"




class ComplaintResourceCreateSerializer(serializers.ModelSerializer):
    resource_id = serializers.PrimaryKeyRelatedField(
        source="resource", queryset=Resource.objects.all(),
        error_messages={"does_not_exist": "Ресурс не знайдено.", "incorrect_type": "Оберіть ресурс із каталогу."},
    )
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), default=1,
        error_messages={
            "invalid": "Введіть коректну кількість.",
            "min_value": "Кількість має бути не меншою за 0,01.",
            "max_digits": "Кількість не може перевищувати 99 999 999,99 і мати більше 2 знаків після коми.",
            "max_whole_digits": "Кількість не може перевищувати 99 999 999,99.",
            "max_decimal_places": "Кількість може мати не більше 2 знаків після коми.",
        },
    )
    unit_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False,
        error_messages={
            "invalid": "Введіть коректну ціну.",
            "min_value": "Ціна не може бути від’ємною.",
            "max_digits": "Ціна не може перевищувати 99 999 999,99 ₴ і мати більше 2 знаків після коми.",
            "max_whole_digits": "Ціна не може перевищувати 99 999 999,99 ₴.",
            "max_decimal_places": "Ціна може мати не більше 2 знаків після коми.",
        },
    )

    class Meta:
        model = ComplaintResource
        fields = ["resource_id", "quantity", "unit_cost", "notes"]

    def create(self, validated_data):
        validated_data.setdefault("unit_cost", validated_data["resource"].unit_cost)
        return super().create(validated_data)
