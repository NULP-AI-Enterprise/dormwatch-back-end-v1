from django.db import models
from django.contrib.auth.models import User


COMPLAINT_STATUS = [
    ('pending', 'На розгляді'),
    ('published', 'Опубліковано'),
    ('denied', 'Відхилено'),
    ('resolved', 'Вирішено')
]


class DormitoryBuilding(models.Model):
    building_id = models.AutoField(primary_key=True)
    number = models.CharField(max_length=10)
    address = models.TextField()

    class Meta:
        db_table = 'dormitory_building'


class DormitoryFloor(models.Model):
    floor_id = models.AutoField(primary_key=True)
    building = models.ForeignKey(DormitoryBuilding, on_delete=models.CASCADE)
    floor_number = models.IntegerField()

    class Meta:
        db_table = 'dormitory_floor'


class DormitoryRoom(models.Model):
    room_id = models.AutoField(primary_key=True)
    floor = models.ForeignKey(DormitoryFloor, on_delete=models.CASCADE)
    room_number = models.CharField(max_length=10)

    class Meta:
        db_table = 'dormitory_room'

class UserProfile(models.Model):
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='profile', 
        primary_key=True
    )
    first_name = models.CharField(max_length=50, blank=True)
    last_name = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_admin = models.BooleanField(default=False)
    room = models.ForeignKey(DormitoryRoom, on_delete=models.CASCADE)
    email = models.CharField(max_length=255)
    photo_url = models.ImageField(upload_to='user_photos/', blank=True, null=True)
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    class Meta:
        db_table = "user_profile"


class ComplaintCategory(models.Model):
    category_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = 'complaint_category'



class Complaint(models.Model):
    complaint_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    room = models.ForeignKey(DormitoryRoom, on_delete=models.CASCADE, null=True, blank=True, related_name='complaints')
    title = models.CharField(max_length=200)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    category = models.ForeignKey(ComplaintCategory, on_delete=models.CASCADE)
    status = models.CharField(max_length=50, choices=COMPLAINT_STATUS, default='pending')
    photo_url = models.ImageField(upload_to='complaint_photos/', blank=True, null=True)
    counter = models.IntegerField(default=0)
    

    def __str__(self):
        return f"{self.title}, ({self.category})"
    
    class Meta:
        db_table = 'complaint'


class Comment(models.Model):
    comment_id = models.AutoField(primary_key=True)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'comment'


class ComplaintVote(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='votes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'complaint_vote'
        unique_together = ('user', 'complaint')
