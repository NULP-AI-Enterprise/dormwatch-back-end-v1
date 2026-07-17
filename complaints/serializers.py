from django.contrib.auth.models import User
from django.conf import settings
from rest_framework import serializers
from .models import Complaint, UserProfile, Comment, DormitoryBuilding, Place, ComplaintCategory, Role, Ticket, Notification, Worker, Announcement
from .image_utils import process_complaint_photo


def _validate_assignable_place(place, exclude_profile_pk=None):
    """Reject assigning a resident to a room that isn't a valid residence.

    A place is unassignable if it is shared (kitchen/laundry/common — a complaint
    location only) or is a private room already at/over capacity. `capacity == 0`
    means "not configured as a residence", so it is never assignable — an admin
    must set a real capacity first. `exclude_profile_pk` drops the profile being
    edited from the occupancy count so re-saving a resident already in the room
    (or just changing their role) does not falsely trip the block.

    Raises serializers.ValidationError({'place_id': ...}) → HTTP 400.
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
        fields = ("building_id", "name", "address", "commandant_phone", "duty_master_phone")


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
    place = PlaceSerializer(read_only=True)
    building = DormitoryBuildingSerializer(read_only=True)
    role = RoleSerializer(read_only=True)
    class Meta:
        model = UserProfile
        fields = ['user', 'first_name', 'last_name', 'email', 'place', 'building', 'photo_url', 'role']


class UpdateUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['first_name', 'last_name', 'email', 'photo_url']


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

class ComplaintSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    place = PlaceSerializer(read_only=True)
    user = UserComplaintSerializer(read_only=True)
    class Meta:
        model = Complaint
        fields = ['complaint_id', 'user', 'title', 'description', 'category', 'status', 'photo_url', 'thumbnail', 'created_at', 'place', 'priority']
        read_only_fields = ['complaint_id', 'created_at', 'user', 'status']

    def create(self, validated_data):
        uploaded_file = validated_data.pop('photo_url', None)
        if uploaded_file:
            result = process_complaint_photo(uploaded_file)
            validated_data['photo_url'] = result['full']
            validated_data['thumbnail'] = result['thumbnail']
        return super().create(validated_data)


class WorkerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Worker
        fields = ['worker_id', 'full_name', 'company', 'phone']


class TicketSerializer(serializers.ModelSerializer):
    worker = WorkerSerializer(read_only=True)
    class Meta:
        model = Ticket
        fields = ['ticket_id', 'worker', 'complaint', 'deadline']


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


class ComplaintStatusSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Complaint
        fields = ['status', 'priority', 'title', 'description', 'category_name']

    
class CommentSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    author_is_admin = serializers.SerializerMethodField()
    class Meta:
        model = Comment
        fields = ['comment_id','complaint','user','user_name', 'author_is_admin', 'description', 'created_at']
        read_only_fields = ("created_at", "user",'complaint')

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()

    def get_author_is_admin(self, obj):
        return bool(obj.user.role and obj.user.role.role_name.lower() in ['admin', 'адміністратор'])


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    place_id = serializers.IntegerField(required=False, allow_null=True)
    building_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_email(self, value):
        email = value.strip().lower()
        domain = email.split('@')[-1] if '@' in email else ''
        allowed = [d.strip().lower() for d in settings.ALLOWED_EMAIL_DOMAINS]
        if domain not in allowed:
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
        building_id = data.get('building_id')
        if DormitoryBuilding.objects.exists() and not building_id:
            raise serializers.ValidationError({'building_id': 'Building selection is required'})
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

