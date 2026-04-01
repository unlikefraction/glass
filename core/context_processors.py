from accounts.models import Carbon


def dashboard_context(request):
    carbon = None
    carbon_id = request.session.get("carbon_id")
    if carbon_id:
        try:
            carbon = Carbon.objects.get(id=carbon_id, is_active=True)
        except Carbon.DoesNotExist:
            carbon = None
    return {"logged_in_carbon": carbon}
