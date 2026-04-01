from rest_framework.authentication import BaseAuthentication


class SiliconTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        silicon = getattr(request, "silicon", None)
        if silicon is not None:
            return (silicon, None)
        return None
