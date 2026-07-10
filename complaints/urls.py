from django.urls import path
from . import views
from . import auth_views
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('auth/login/', auth_views.LoginView.as_view(), name='auth-login'),
    path('auth/register/', auth_views.RegisterView.as_view(), name='auth-register'),
    path('auth/refresh/', auth_views.CookieTokenRefreshView.as_view(), name='auth-refresh'),
    path('auth/logout/', auth_views.LogoutView.as_view(), name='auth-logout'),
    path('buildings/', auth_views.BuildingListView.as_view(), name='buildings'),
    path('places/', auth_views.PlaceListView.as_view(), name='places'),
    path('complaints/', views.ComplaintView.as_view(), name='complaint'),
    path('complaints/<int:complaint_id>/', views.ComplaintDetailView.as_view(), name = 'user-complaint-detail'),
    path('me/complaints/', views.UserComplaintView.as_view(), name='user-complaint'),
    path('me/complaints/<int:complaint_id>/', views.UserComplaintDetailView.as_view(), name = 'user-complaint-detail'),
    path('me/tickets/', views.UserTicketView.as_view(), name='user-tickets'),
    path('complaints/<int:complaint_id>/comments/', views.CommentListView.as_view(), name="comments"),
    path('comments/<int:comment_id>/', views.CommentDeleteView.as_view(), name="delete-comment"),
    path('admin/complaints/<int:complaint_id>/status/', views.AdminComplaintStatusView.as_view(), name = "complaint-status-change"),
    path('admin/users/<str:user_id>/set-role/', views.UpdateUserRoleView.as_view(), name='set-user-role'),
    path('profile/', views.UserProfileView.as_view(), name="user-profile"),
    path('profile/change-room/', views.ChangeUserRoomView.as_view(), name='profile-change-room'),
    path('tickets/', views.TicketView.as_view(), name='tickets'),
    path('tickets/<int:ticket_id>/', views.TicketDetailView.as_view(), name='ticket-detail'),
    path('admin/employees/', views.EmployeeListView.as_view(), name='admin-employees'),
    path('categories/', views.CategoryListView.as_view(), name='categories'),
    path('admin/categories/', views.AdminCategoryCreateView.as_view(), name='admin-categories'),
    path('admin/categories/<int:category_id>/', views.AdminCategoryDetailView.as_view(), name='admin-category-detail'),
    path('admin/buildings/', views.AdminBuildingCreateView.as_view(), name='admin-buildings'),
    path('admin/buildings/<int:building_id>/', views.AdminBuildingDetailView.as_view(), name='admin-building-detail'),
    path('admin/places/<int:place_id>/', views.AdminPlaceDetailView.as_view(), name='admin-place-detail'),
    path('notifications/', views.NotificationListView.as_view(), name='notifications-list'),
    path('notifications/<int:notification_id>/', views.NotificationMarkReadView.as_view(), name='notification-mark-read'),
    path('notifications/mark-all-read/', views.NotificationMarkAllReadView.as_view(), name='notifications-mark-all-read'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)