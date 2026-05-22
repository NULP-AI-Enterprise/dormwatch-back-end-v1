from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('complaints/', views.ComplaintView.as_view(), name='complaint'),
    path('complaints/<int:complaint_id>/', views.ComplaintDetailView.as_view(), name = 'user-complaint-detail'),
    path('me/complaints/', views.UserComplaintView.as_view(), name='user-complaint'),
    path('me/complaints/<int:complaint_id>/', views.UserComplaintDetailView.as_view(), name = 'user-complaint-detail'),
    path('complaints/<int:complaint_id>/comments/', views.CommentListView.as_view(), name="comments"),
    path('comments/<int:comment_id>/', views.CommentDeleteView.as_view(), name="delete-comment"),
    path('admin/complaints/<int:complaint_id>/status/', views.AdminComplaintStatusView.as_view(), name = "complaint-status-change"),
    path('admin/users/<str:user_id>/set-admin/', views.UpdateUserStatusView.as_view(), name='set-user-admin'),
    path('profile/', views.UserProfileView.as_view(), name="user-profile"),
    path('profile/change-room/', views.UpdateUserRoomView.as_view(), name="room-change"),
    path('complaints/<int:complaint_id>/counter/', views.ComplaintCounterView.as_view(), name='complaint-counter'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)