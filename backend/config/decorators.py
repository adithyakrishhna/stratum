"""
Project-wide view decorators.

api_login_required — replaces Django's @login_required for API views.
Django's @login_required redirects unauthenticated requests to the HTML
login page (302).  For JSON API endpoints that redirect breaks the React
SPA: axios follows the redirect, receives HTML, and the frontend cannot
tell whether the request succeeded or failed.  This decorator returns 401
JSON instead so the React ProtectedRoute can handle auth failures correctly.
"""
from functools import wraps

from django.http import JsonResponse


def api_login_required(view_func):
    """
    Decorator for API views that returns 401 JSON for unauthenticated requests
    instead of Django's default 302 redirect to the login page.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Authentication required.',
                    'data': None,
                    'meta': {},
                },
                status=401,
            )
        return view_func(request, *args, **kwargs)
    return wrapper
