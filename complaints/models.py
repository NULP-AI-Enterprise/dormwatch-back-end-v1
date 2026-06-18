from django.db import models
from django.contrib.auth.models import User


COMPLAINT_STATUS = [
    ('pending', 'На розгляді'),
    ('published', 'Опубліковано'),
    ('denied', 'Відхилено'),
    ('resolved', 'Вирішено')
]


class Role(models.Model):
    role_id = models.AutoField(primary_key=True)
    role_name = models.CharField(max_length=255)

    class Meta:
        db_table = 'role'


class DormitoryBuilding(models.Model):
    building_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    address = models.TextField()

    class Meta:
        db_table = 'dormitory_building'


class Place(models.Model):
    place_id = models.AutoField(primary_key=True)
    place_name = models.CharField(max_length=255)
    building = models.ForeignKey(DormitoryBuilding, on_delete=models.CASCADE)

    class Meta:
        db_table = 'place'


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
    email = models.CharField(max_length=255)
    photo_url = models.ImageField(upload_to='user_photos/', blank=True, null=True)
    login = models.CharField(max_length=255, blank=True, null=True)
    password = models.CharField(max_length=255, blank=True, null=True)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, null=True, blank=True)
    place = models.ForeignKey(Place, on_delete=models.CASCADE, null=True, blank=True)
    
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
    place = models.ForeignKey(Place, on_delete=models.CASCADE, null=True, blank=True, related_name='complaints')
    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=50, choices=COMPLAINT_STATUS, default='pending')
    photo_url = models.ImageField(upload_to='complaint_photos/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    category = models.ForeignKey(ComplaintCategory, on_delete=models.CASCADE)
    priority = models.CharField(max_length=50, blank=True, null=True)
    

    def __str__(self):
        return f"{self.title}, ({self.category})"
    
    class Meta:
        db_table = 'complaint'


class Ticket(models.Model):
    ticket_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE)
    deadline = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ticket'


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
