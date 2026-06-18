from rest_framework import serializers
from .models import Complaint, UserProfile, Comment, DormitoryBuilding, Place, ComplaintCategory, Role, Ticket



class DormitoryBuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model = DormitoryBuilding
        fields = ("building_id", "name", "address")


class PlaceSerializer(serializers.ModelSerializer):
    building = DormitoryBuildingSerializer()

    class Meta:
        model = Place
        fields = ("place_id", "place_name", "building")


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ("role_id", "role_name")


class UserSerializer(serializers.ModelSerializer):
    place = PlaceSerializer(read_only=True)
    role = RoleSerializer(read_only=True)
    class Meta:
        model = UserProfile
        fields = ['user', 'first_name', 'last_name', 'email', 'place', 'photo_url', 'role']


class UpdateUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['first_name', 'last_name', 'email', 'photo_url']


class UpdateUserPlaceSerializer(serializers.Serializer):
    place_id = serializers.IntegerField()


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplaintCategory
        fields = ['name']


class UserComplaintSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['first_name', 'last_name', 'photo_url']

class ComplaintSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    place = PlaceSerializer(read_only=True)
    user = UserComplaintSerializer(read_only=True)
    class Meta:
        model = Complaint
        fields = ['complaint_id', 'user', 'title', 'description', 'category', 'status', 'photo_url', 'created_at', 'place', 'priority']
        read_only_fields = ['complaint_id', 'created_at', 'user', 'status']


class TicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ['ticket_id', 'user', 'complaint', 'deadline']


class UpdateUserRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['role']


class ComplaintStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = ['status']

    
class CommentSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    class Meta:
        model = Comment
        fields = ['comment_id','complaint','user','user_name', 'description', 'created_at']
        read_only_fields = ("created_at", "user",'complaint')

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()
