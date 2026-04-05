from django.urls import path

from messaging.views import (
    MessageAttachmentDownloadView,
    SendMessageApiView,
    ThreadIndexView,
    ThreadListApiView,
    ThreadMessagesApiView,
)

urlpatterns = [
    path("thread/", ThreadIndexView.as_view(), name="thread_index"),
    path("api/threads/", ThreadListApiView.as_view(), name="thread_list"),
    path("api/threads/<str:username>/", ThreadMessagesApiView.as_view(), name="thread_messages"),
    path("api/threads/<str:username>/send/", SendMessageApiView.as_view(), name="thread_send"),
    path("api/messages/<int:message_id>/attachment/", MessageAttachmentDownloadView.as_view(), name="message_attachment"),
]
