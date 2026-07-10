from django.contrib.auth.models import User
from django.conf import settings
from rest_framework import serializers
from .models import Complaint, UserProfile, Comment, DormitoryBuilding, Place, ComplaintCategory, Role, Ticket, Notification, Worker
from .image_utils import process_complaint_photo



class DormitoryBuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model = DormitoryBuilding
        fields = ("building_id", "name", "address", "commandant_phone", "duty_master_phone")


class PlaceSerializer(serializers.ModelSerializer):
    building = DormitoryBuildingSerializer()

    class Meta:
        model = Place
        fields = ("place_id", "place_name", "building")


class PlaceWriteSerializer(serializers.ModelSerializer):
    building_id = serializers.PrimaryKeyRelatedField(
        source='building', queryset=DormitoryBuilding.objects.all()
    )

    class Meta:
        model = Place
        fields = ("place_id", "place_name", "building_id")


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


class ComplaintStatusSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Complaint
        fields = ['status', 'priority', 'title', 'description', 'category_name']

    
class CommentSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    class Meta:
        model = Comment
        fields = ['comment_id','complaint','user','user_name', 'description', 'created_at']
        read_only_fields = ("created_at", "user",'complaint')

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()


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

