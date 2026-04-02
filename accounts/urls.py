from django.urls import path

from accounts.views import (
    CarbonProfileView,
    CarbonUpdateView,
    DashboardView,
    GoogleAuthCompleteView,
    GoogleCallbackPageView,
    LogoutView,
    ProfileView,
    SiliconCreateView,
)

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("auth/google/callback/", GoogleCallbackPageView.as_view(), name="google_callback"),
    path("auth/google/complete/", GoogleAuthCompleteView.as_view(), name="google_complete"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("api/carbon/profile/", CarbonProfileView.as_view(), name="carbon_profile"),
    path("api/carbon/update/", CarbonUpdateView.as_view(), name="carbon_update"),
    path("api/silicons/create/", SiliconCreateView.as_view(), name="silicon_create"),
]
