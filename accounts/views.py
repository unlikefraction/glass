from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views import View
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from rest_framework.views import APIView

from accounts.models import Carbon
from core.utils import api_response, error_response
from syncer.models import ConnectorCode, Silicon


def _normalize_username(value):
    return (value or "").strip().lower()


def _next_available_username(base):
    base = _normalize_username(base) or "carbon"
    candidate = base
    suffix = 2
    while Carbon.objects.filter(username=candidate).exists():
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def _require_carbon(request):
    carbon_id = request.session.get("carbon_id")
    if not carbon_id:
        return None
    try:
        return Carbon.objects.get(id=carbon_id, is_active=True)
    except Carbon.DoesNotExist:
        return None


class DashboardView(View):
    def get(self, request):
        carbon = _require_carbon(request)
        if not carbon:
            return render(
                request,
                "accounts/login.html",
                {"google_client_id": settings.GOOGLE_CLIENT_ID},
            )

        silicons = Silicon.objects.filter(owner=carbon).order_by("username").prefetch_related("connector_codes")
        latest_codes = {}
        for code in ConnectorCode.objects.filter(silicon__owner=carbon, is_active=True).order_by("-created_at"):
            latest_codes.setdefault(code.silicon_id, code)
        return render(
            request,
            "accounts/dashboard.html",
            {"carbon": carbon, "silicons": silicons, "latest_codes": latest_codes},
        )


class GoogleCallbackPageView(View):
    def get(self, request):
        return render(request, "accounts/google_callback.html")


class GoogleAuthCompleteView(APIView):
    def post(self, request):
        credential = request.data.get("credential") or request.data.get("id_token")
        if not credential:
            return error_response("credential is required.")
        if not settings.GOOGLE_CLIENT_ID:
            return error_response("GOOGLE_CLIENT_ID is not configured.", status=500)

        try:
            payload = id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
        except Exception:
            return error_response("Invalid Google credential.", status=401)

        email = (payload.get("email") or "").lower().strip()
        google_sub = payload.get("sub") or ""
        if not email or not google_sub:
            return error_response("Google did not return a usable identity.", status=400)

        with transaction.atomic():
            carbon, created = Carbon.objects.get_or_create(
                google_sub=google_sub,
                defaults={
                    "email": email,
                    "username": _next_available_username(email.split("@", 1)[0]),
                    "name": payload.get("name", ""),
                    "avatar_url": payload.get("picture", ""),
                },
            )
            if not created:
                changed = False
                if carbon.email != email:
                    carbon.email = email
                    changed = True
                if payload.get("name") and carbon.name != payload["name"]:
                    carbon.name = payload["name"]
                    changed = True
                if payload.get("picture") and carbon.avatar_url != payload["picture"]:
                    carbon.avatar_url = payload["picture"]
                    changed = True
                if changed:
                    carbon.save(update_fields=["email", "name", "avatar_url"])

        request.session["carbon_id"] = carbon.id
        return api_response(
            {"username": carbon.username, "email": carbon.email, "name": carbon.name},
            meta={"username": "Carbon username", "email": "Carbon email", "name": "Display name"},
        )


class LogoutView(View):
    def get(self, request):
        request.session.flush()
        return HttpResponseRedirect("/accounts/dashboard/")


class CarbonProfileView(APIView):
    def get(self, request):
        carbon = _require_carbon(request)
        if not carbon:
            return error_response("Not authenticated.", status=401)
        return api_response(
            {
                "username": carbon.username,
                "email": carbon.email,
                "name": carbon.name,
                "created_at": carbon.created_at.isoformat(),
            },
            meta={"username": "Carbon username", "email": "Carbon email", "name": "Display name", "created_at": "Creation time"},
        )


class SiliconCreateView(APIView):
    def post(self, request):
        carbon = _require_carbon(request)
        if not carbon:
            return error_response("Not authenticated.", status=401)

        username = _normalize_username(request.data.get("username"))
        display_name = (request.data.get("display_name") or "").strip()
        if not username:
            return error_response("username is required.")
        if not username.endswith("silicon"):
            return error_response("Silicon usernames must end with 'silicon'.")
        if Silicon.objects.filter(username=username).exists():
            return error_response("That silicon username already exists.")

        silicon = Silicon.objects.create(owner=carbon, username=username, display_name=display_name)
        return api_response(
            {
                "username": silicon.username,
                "display_name": silicon.display_name,
                "api_key": silicon.api_key,
            },
            meta={
                "username": "Silicon username",
                "display_name": "Optional display name",
                "api_key": "Bearer token for silicon API requests",
            },
            status=201,
        )
