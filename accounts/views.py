from urllib.parse import urlencode

import requests as http_requests
from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views import View
from rest_framework.views import APIView

from accounts.models import Carbon
from core.utils import api_response, error_response
from syncer.models import ConnectorCode, Silicon


def _build_google_auth_url():
    """Build Google OAuth implicit flow URL."""
    if not settings.GOOGLE_CLIENT_ID:
        return None
    redirect_uri = settings.GLASS_PUBLIC_URL.rstrip("/") + "/accounts/auth/google/callback/"
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "token",
        "scope": "profile email",
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def _get_google_userinfo(access_token):
    """Validate a Google access token by calling the userinfo API."""
    try:
        resp = http_requests.get(
            "https://www.googleapis.com/oauth2/v1/userinfo?alt=json",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


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
                {"google_auth_url": _build_google_auth_url()},
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
        access_token = (request.data.get("access_token") or "").strip()
        if not access_token:
            return error_response("access_token is required.")

        google_data = _get_google_userinfo(access_token)
        if not google_data:
            return error_response("Invalid or expired Google token.", status=401)

        email = (google_data.get("email") or "").lower().strip()
        verified = google_data.get("verified_email", False)
        google_sub = google_data.get("id") or ""

        if not email:
            return error_response("Google did not return an email.", status=400)
        if not verified:
            return error_response("Email is not verified by Google.", status=400)
        if not google_sub:
            return error_response("Google did not return a usable identity.", status=400)

        name = google_data.get("name", "")
        picture = google_data.get("picture", "")

        with transaction.atomic():
            carbon, created = Carbon.objects.get_or_create(
                google_sub=google_sub,
                defaults={
                    "email": email,
                    "username": _next_available_username(email.split("@", 1)[0]),
                    "name": name,
                    "avatar_url": picture,
                },
            )
            if not created:
                changed = False
                if carbon.email != email:
                    carbon.email = email
                    changed = True
                if name and carbon.name != name:
                    carbon.name = name
                    changed = True
                if picture and carbon.avatar_url != picture:
                    carbon.avatar_url = picture
                    changed = True
                if changed:
                    carbon.save(update_fields=["email", "name", "avatar_url"])

        request.session["carbon_id"] = carbon.id
        return api_response(
            {"username": carbon.username, "email": carbon.email, "name": carbon.name},
            meta={"username": "Carbon username", "email": "Carbon email", "name": "Display name"},
        )


class ProfileView(View):
    def get(self, request):
        carbon = _require_carbon(request)
        if not carbon:
            return HttpResponseRedirect("/accounts/dashboard/")
        return render(request, "accounts/profile.html", {"carbon": carbon})


class CarbonUpdateView(APIView):
    def post(self, request):
        carbon = _require_carbon(request)
        if not carbon:
            return error_response("Not authenticated.", status=401)
        username = _normalize_username(request.data.get("username"))
        if not username:
            return error_response("Username is required.")
        if len(username) < 2:
            return error_response("Username must be at least 2 characters.")
        if Carbon.objects.filter(username=username).exclude(id=carbon.id).exists():
            return error_response("That username is already taken.")
        carbon.username = username
        carbon.save(update_fields=["username"])
        return api_response({"username": carbon.username})


class LogoutView(View):
    def get(self, request):
        request.session.flush()
        return HttpResponseRedirect("/")


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
