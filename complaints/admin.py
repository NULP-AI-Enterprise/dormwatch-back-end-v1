from django.contrib import admin
from .models import Complaint, UserProfile, Comment, DormitoryBuilding, ComplaintCategory, Role, Ticket, Place
# Register your models here.
class ComplaintAdmin(admin.ModelAdmin):
    raw_id_fields = ['user', 'place', 'category']

class UserProfileAdmin(admin.ModelAdmin):
    raw_id_fields = ['user', 'place', 'building', 'role']

class CommentAdmin(admin.ModelAdmin):
    raw_id_fields = ['complaint', 'user']

class TicketAdmin(admin.ModelAdmin):
    raw_id_fields = ['complaint', 'worker']

admin.site.register(Complaint, ComplaintAdmin)
admin.site.register(UserProfile, UserProfileAdmin)
admin.site.register(Role)
admin.site.register(DormitoryBuilding)
admin.site.register(ComplaintCategory)
admin.site.register(Comment, CommentAdmin)
admin.site.register(Ticket, TicketAdmin)
admin.site.register(Place)