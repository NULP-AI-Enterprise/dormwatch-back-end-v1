from django.contrib import admin
from .models import Complaint, UserProfile, Comment, DormitoryRoom, DormitoryBuilding, DormitoryFloor, ComplaintCategory
# Register your models here.
admin.site.register(Complaint)
admin.site.register(UserProfile)
admin.site.register(DormitoryRoom)
admin.site.register(DormitoryBuilding)
admin.site.register(DormitoryFloor)
admin.site.register(ComplaintCategory)
admin.site.register(Comment)