from django.urls import path

from accounts.views import (
    CarbonProfileView,
    DashboardView,
    GoogleAuthCompleteView,
    GoogleCallbackPageView,
    LogoutView,
    SiliconCreateView,
)

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("auth/google/callback/", GoogleCallbackPageView.as_view(), name="google_callback"),
    path("auth/google/complete/", GoogleAuthCompleteView.as_view(), name="google_complete"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("api/carbon/profile/", CarbonProfileView.as_view(), name="carbon_profile"),
    path("api/silicons/create/", SiliconCreateView.as_view(), name="silicon_create"),
]
