from django.urls import path

from messaging.views import SendMessageApiView, ThreadIndexView, ThreadListApiView, ThreadMessagesApiView

urlpatterns = [
    path("thread/", ThreadIndexView.as_view(), name="thread_index"),
    path("api/threads/", ThreadListApiView.as_view(), name="thread_list"),
    path("api/threads/<str:username>/", ThreadMessagesApiView.as_view(), name="thread_messages"),
    path("api/threads/<str:username>/send/", SendMessageApiView.as_view(), name="thread_send"),
]
