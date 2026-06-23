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
    path('admin/users/<str:user_id>/set-role/', views.UpdateUserRoleView.as_view(), name='set-user-role'),
    path('profile/', views.UserProfileView.as_view(), name="user-profile"),
    path('complaints/<int:complaint_id>/vote/', views.ComplaintVoteView.as_view(), name='complaint-vote'),
    path('tickets/', views.TicketView.as_view(), name='tickets'),
    path('tickets/<int:ticket_id>/', views.TicketDetailView.as_view(), name='ticket-detail'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)