from rest_framework import serializers
from .models import Complaint, UserProfile, Comment, DormitoryBuilding, DormitoryFloor, DormitoryRoom, ComplaintCategory



class DormitoryBuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model = DormitoryBuilding
        fields = ("number", "address")


class DormitoryFloorSerializer(serializers.ModelSerializer):
    building = DormitoryBuildingSerializer()

    class Meta:
        model = DormitoryFloor
        fields = ("floor_number", "building")


class DormitoryRoomSerializer(serializers.ModelSerializer):
    floor = DormitoryFloorSerializer()

    class Meta:
        model = DormitoryRoom
        fields = ("room_number", "floor")


class UserSerializer(serializers.ModelSerializer):
    room = DormitoryRoomSerializer(read_only=True)
    class Meta:
        model = UserProfile
        fields = ['user', 'first_name', 'last_name', 'email', 'room', 'photo_url', 'is_admin']


class UpdateUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['first_name', 'last_name', 'email', 'photo_url']


class UpdateUserRoomSerializer(serializers.Serializer):
    building_number = serializers.CharField()
    floor_number = serializers.IntegerField()
    room_number = serializers.CharField()


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
    room = DormitoryRoomSerializer(read_only=True)
    user = UserComplaintSerializer(read_only=True)
    class Meta:
        model = Complaint
        fields = ['complaint_id', 'user', 'title', 'description', 'category', 'status', 'photo_url', 'created_at', 'counter','room']
        read_only_fields = ['counter', 'complaint_id', 'created_at', 'user', 'status']





class UpdateAdminStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['is_admin']
        read_only_fields = []


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


class ComplaintCountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = ['counter']
        read_only_fields = ['counter']

