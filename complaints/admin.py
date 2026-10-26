from django.contrib import admin
from .models import Complaint, UserProfile, Comment, DormitoryBuilding, ComplaintCategory, Role, Place, Announcement
# Register your models here.
class ComplaintAdmin(admin.ModelAdmin):
    raw_id_fields = ['user', 'place', 'category']

class UserProfileAdmin(admin.ModelAdmin):
    raw_id_fields = ['user', 'place', 'building', 'role']

class CommentAdmin(admin.ModelAdmin):
    raw_id_fields = ['complaint', 'user']

    def get_readonly_fields(self, request, obj=None):
        # An author cannot be reassigned to bypass the deletion ownership check.
        fields = super().get_readonly_fields(request, obj)
        return (*fields, 'user') if obj is not None else fields

    def has_delete_permission(self, request, obj=None):
        # No bulk deletion or staff/superuser override for another author's comment.
        return bool(
            obj is not None
            and obj.user_id == request.user.pk
            and super().has_delete_permission(request, obj)
        )


admin.site.register(Complaint, ComplaintAdmin)
admin.site.register(UserProfile, UserProfileAdmin)
admin.site.register(Role)
admin.site.register(DormitoryBuilding)
admin.site.register(ComplaintCategory)
admin.site.register(Comment, CommentAdmin)
admin.site.register(Place)
admin.site.register(Announcement)
