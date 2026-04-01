from django.conf import settings
from django.shortcuts import render
from django.views import View

from syncer.models import Silicon


class HomeView(View):
    def get(self, request):
        return render(
            request,
            "home.html",
            {
                "silicon_count": Silicon.objects.filter(is_active=True).count(),
                "public_url": settings.GLASS_PUBLIC_URL,
            },
        )
