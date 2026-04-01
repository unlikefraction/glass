from rest_framework.response import Response


def api_response(data, meta=None, status=200):
    if meta:
        data["_meta"] = meta
    return Response(data, status=status)


def error_response(message, status=400):
    return Response({"error": message}, status=status)
