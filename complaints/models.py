from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User
from django.utils import timezone
import uuid


# Canonical lifecycle vocabulary. Status slugs are byte-identical across the
# server and the web app — no alias layer exists anywhere else. The first five
# form the resident-visible stepper order; the last three are terminal.
COMPLAINT_STATUS_ORDER = ['pending', 'approved', 'in_progress', 'review', 'resolved']
COMPLAINT_STATUS = [
    ('pending', 'Очікує'),
    ('approved', 'Схвалено'),
    ('in_progress', 'В роботі'),
    ('review', 'На перевірці'),
    ('resolved', 'Вирішено'),
    ('rejected', 'Відхилено'),
    ('not_accepted', 'Не прийнято'),
    ('withdrawn', 'Скасовано')
]
# Progress nuance lives in timestamps, not extra statuses: entering a state
# stamps its timestamp once, undoing backwards out of it clears the stamp.
STATUS_TIMESTAMP_FIELD = {
    'in_progress': 'started_at',
    'review': 'finished_at',
    'resolved': 'resolved_at',
}

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
    is_email_verified = models.BooleanField(default=False)

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

    # --- Assignment + lifecycle (absorbed from the deleted Ticket model) ---
    # Assigned contractor. SET_NULL so deleting a worker unassigns their
    # complaints rather than deleting them.
    worker = models.ForeignKey('Worker', on_delete=models.SET_NULL, null=True, blank=True, related_name='complaints')
    deadline = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    work_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    rework_reason = models.TextField(blank=True)
    # Re-file chains: follow_up_of points at the complaint this one re-files,
    # root denormalizes the chain head at creation so lists and reports can
    # group a whole chain by it.
    follow_up_of = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='follow_ups',
    )
    root = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='follow_up_chain',
    )
    # Soft delete once lifecycle data exists: archived rows vanish from lists
    # and feeds but stay readable for reports and pay disputes. Hard delete is
    # only allowed before a worker is assigned.
    archived = models.BooleanField(default=False)
    archived_by = models.ForeignKey(
        UserProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='archived_complaints',
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'complaint'
        constraints = [
            # At most one OPEN follow-up per source complaint (a re-file chain
            # may hold several closed children, but never two live ones). The
            # partial index makes a double-tap re-file fail at the DB level,
            # even under concurrent submits.
            models.UniqueConstraint(
                fields=['follow_up_of'],
                condition=Q(status__in=COMPLAINT_STATUS_ORDER),
                name='unique_open_follow_up_per_source',
            ),
        ]

    def __str__(self):
        return f"{self.title}, ({self.category})"

    def transition(self, new_status):
        '''The single lifecycle mutation point. Every endpoint changes status
        through here so `status` and its timestamps (started_at / finished_at /
        resolved_at) are written together — no call site hand-writes both
        sides of the invariant. Entering in_progress/review/resolved stamps
        the matching timestamp once; moving backwards out of a stamped state
        (an undo) clears it. Terminal states keep all stamps.'''
        if new_status not in dict(COMPLAINT_STATUS):
            raise ValueError(f"Unknown complaint status: {new_status!r}")
        old = self.status
        now = timezone.now()
        self.status = new_status
        stamp = STATUS_TIMESTAMP_FIELD.get(new_status)
        if stamp and getattr(self, stamp) is None:
            setattr(self, stamp, now)
        old_stamp = STATUS_TIMESTAMP_FIELD.get(old)
        if (
            old_stamp
            and old in COMPLAINT_STATUS_ORDER
            and new_status in COMPLAINT_STATUS_ORDER
            and COMPLAINT_STATUS_ORDER.index(new_status) < COMPLAINT_STATUS_ORDER.index(old)
        ):
            setattr(self, old_stamp, None)
        self.save(update_fields=['status', 'started_at', 'finished_at', 'resolved_at'])

    def log_event(self, action, actor=None):
        '''Append an entry to the lifecycle event log (assignment changes,
        stamps, undos, archiving). Read surface: history line on the
        complaint panel.'''
        return ComplaintEvent.objects.create(complaint=self, actor=actor, action=action)


class ComplaintEvent(models.Model):
    '''Append-only lifecycle log: who did what to a complaint and when. Covers
    assignment/unassignment/reassignment, started_at/finished_at stamps and
    their undos, and archiving — so mid-job reassignment keeps per-worker
    attribution honest and proxy stamps carry provenance. Rows are never
    edited or deleted.'''
    COMPLAINT_EVENT_ACTION = [
        ('assigned', 'Призначено'),
        ('unassigned', 'Знято з виконання'),
        ('reassigned', 'Перепризначено'),
        ('started', 'Взято в роботу'),
        ('started_undo', 'Скасовано початок робіт'),
        ('finished', 'Виконано'),
        ('finished_undo', 'Скасовано виконання'),
        ('archived', 'Архівовано'),
    ]
    event_id = models.AutoField(primary_key=True)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='events')
    actor = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaint_events')
    action = models.CharField(max_length=50, choices=COMPLAINT_EVENT_ACTION)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'complaint_event'
        ordering = ['created_at', 'event_id']

    def __str__(self):
        return f"{self.complaint_id}: {self.action}"


class Worker(models.Model):
    '''An external contractor who fixes reported issues. Assignment target for
    complaints. A worker MAY hold an app account (provisioned via invite):
    account = a UserProfile with role `worker`, linked 1:1 from here — the
    account is a capability, never a stored worker type. Account-less workers
    work through printed work-orders + admin proxy stamps. One account = one
    worker; no shared crew logins.'''
    worker_id = models.AutoField(primary_key=True)
    full_name = models.CharField(max_length=255)
    company = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    # Nullable 1:1 link to the provisioned login (UserProfile, role `worker`).
    # SET_NULL so unlinking/deleting the account keeps the worker assignable.
    account = models.OneToOneField(
        UserProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='worker',
    )

    def __str__(self):
        return self.full_name

    class Meta:
        db_table = 'worker'


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


class PendingTransitionNotice(models.Model):
    '''Staged lifecycle notification. A transition does not write a
    Notification row directly — it stages one here with ready_at set past the
    undo window. The lazy sweep at read time (see views._sweep_transition_notices,
    same pattern as announcement pin expiry) materializes staged rows into real
    notifications once their window passes. Re-staging on a newer transition
    REPLACES this row (unique per complaint+recipient), so an undo inside the
    window never pings anyone.'''
    notice_id = models.AutoField(primary_key=True)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='pending_notices')
    recipient = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='pending_transition_notices')
    title = models.CharField(max_length=255)
    message = models.TextField()
    ready_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = 'pending_transition_notice'
        constraints = [
            models.UniqueConstraint(
                fields=['complaint', 'recipient'],
                name='unique_pending_notice_per_recipient',
            )
        ]



class InviteToken(models.Model):
    token = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    building_id = models.IntegerField(null=True, blank=True)
    place_id = models.IntegerField(null=True, blank=True)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        db_table = 'invite_token'
        ordering = ['-created_at']
        
        
class EmailVerificationCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_verification_codes')
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        db_table = 'email_verification_code'


class PasswordResetCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_codes')
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        db_table = 'password_reset_code'

        
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
