"""
Project-wide Django middleware.

AdminAccessMiddleware — redirects authenticated non-staff users away from
/admin/.  Without this, Django admin shows those users a "log in as a
different account" option which, when clicked, logs them out of their
GitHub OAuth session.  They then navigate to /dashboard/ and see the
Stratum login page, which looks like "admin login in the dashboard".
"""
from django.http import HttpResponseRedirect


class AdminAccessMiddleware:
    """
    Redirect authenticated non-staff users away from /admin/ immediately.

    Staff users (is_staff=True) pass through to the normal admin site.
    Unauthenticated users also pass through so the admin login form can
    accept superuser credentials if needed.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.path.startswith('/admin/')
            and request.user.is_authenticated
            and not request.user.is_staff
        ):
            return HttpResponseRedirect('/')
        return self.get_response(request)
