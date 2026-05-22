from rest_framework.permissions import BasePermission, IsAdminUser
from .models import UserProfile

class IsCustomAdmin(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        try:
            profile = UserProfile.objects.get(user=request.user)
            return profile.is_admin
        except UserProfile.DoesNotExist:
            return False
        
class IsAdminOrCustomAdmin(BasePermission):
    def has_permission(self, request, view):
        return IsAdminUser().has_permission(request, view) or IsCustomAdmin().has_permission(request, view)