from datetime import timedelta

from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from syncer.models import Silicon


class SiliconTokenMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request.silicon = None
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth.startswith("Bearer "):
            return
        token = auth[7:].strip()
        try:
            silicon = Silicon.objects.select_related("owner").get(api_key=token, is_active=True)
        except Silicon.DoesNotExist:
            return

        if silicon.api_key_last_used and timezone.now() - silicon.api_key_last_used > timedelta(days=30):
            return

        silicon.api_key_last_used = timezone.now()
        silicon.save(update_fields=["api_key_last_used"])
        request.silicon = silicon
