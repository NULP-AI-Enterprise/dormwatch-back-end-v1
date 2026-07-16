from django.db import models
from django.contrib.auth.models import User


COMPLAINT_STATUS = [
    ('pending', 'На розгляді'),
    ('published', 'Опубліковано'),
    ('denied', 'Відхилено'),
    ('resolved', 'Вирішено')
]
COMPLAINT_PRIORITY = [
    ('low', 'Низький'),
    ('medium', 'Середній'),
    ('high', 'Високий'),
    ('critical', 'Критичний')
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
    commandant_phone = models.CharField(max_length=32, blank=True)
    duty_master_phone = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = 'dormitory_building'


class Place(models.Model):
    place_id = models.AutoField(primary_key=True)
    place_name = models.CharField(max_length=255)
    building = models.ForeignKey(DormitoryBuilding, on_delete=models.CASCADE)
    # 0 = not a residence (kitchen/common area). A positive value is the number
    # of residents the room can hold.
    capacity = models.PositiveIntegerField(default=0)
    # A shared room (kitchen/laundry/common) is a complaint location only and is
    # NEVER a resident's assigned residence.
    is_shared = models.BooleanField(default=False)

    class Meta:
        db_table = 'place'
        constraints = [
            models.UniqueConstraint(
                fields=['building', 'place_name'],
                name='unique_building_place_name'
            )
        ]


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
    building = models.ForeignKey(
        DormitoryBuilding, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='residents',
    )

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
    place = models.ForeignKey(Place, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaints')
    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=50, choices=COMPLAINT_STATUS, default='pending')
    photo_url = models.ImageField(upload_to='complaint_photos/', blank=True, null=True)
    thumbnail = models.ImageField(upload_to='complaint_photos/thumbnails/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when the complaint transitions INTO status 'resolved' (by admin or the
    # owner); cleared to None if it is later moved back out of resolved. Powers
    # an honest date-range filter for the completed-tickets report.
    resolved_at = models.DateTimeField(null=True, blank=True)
    category = models.ForeignKey(ComplaintCategory, on_delete=models.SET_NULL, null=True, blank=True)
    priority = models.CharField(max_length=50, choices=COMPLAINT_PRIORITY, default='medium')
    

    def __str__(self):
        return f"{self.title}, ({self.category})"
    
    class Meta:
        db_table = 'complaint'


class Worker(models.Model):
    '''An external contractor who fixes reported issues. Workers never use the
    app — they only receive a printed work-order. They are assignable to tickets
    but have no login/account (unlike a UserProfile).'''
    worker_id = models.AutoField(primary_key=True)
    full_name = models.CharField(max_length=255)
    company = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)

    def __str__(self):
        return self.full_name

    class Meta:
        db_table = 'worker'


class Ticket(models.Model):
    ticket_id = models.AutoField(primary_key=True)
    # Assigned contractor. SET_NULL so deleting a worker unassigns their tickets
    # rather than deleting the work orders.
    worker = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True)
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


class Notification(models.Model):
    notification_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    complaint = models.ForeignKey(Complaint, on_delete=models.SET_NULL, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification'
        ordering = ['-created_at']


class Announcement(models.Model):
    announcement_id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    body = models.TextField()
    # Nullable = GLOBAL (visible to every building). Set = scoped to one building.
    building = models.ForeignKey(
        DormitoryBuilding, on_delete=models.CASCADE,
        null=True, blank=True, related_name='announcements',
    )
    is_pinned = models.BooleanField(default=False)
    # Calendar day the notice stops being "active". Expired = expires_at < today.
    # Expiry only marks/hides (dashboard widget drops it, resident page shows it
    # archived) — it never deletes. Crossing this date also clears is_pinned via a
    # lazy sweep at read time (there is no scheduler; see views._sweep_expired_pins).
    expires_at = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        UserProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='authored_announcements',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    class Meta:
        db_table = 'announcement'
        ordering = ['-created_at']



