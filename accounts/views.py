from django.http import HttpResponse


def login_view(request):
    return HttpResponse("Subscript Login (Placeholder for Phase 2 auth / Member 2 template)")


def logout_view(request):
    return HttpResponse("Subscript Logout (Placeholder)")
