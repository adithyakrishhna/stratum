from django.contrib.auth.decorators import login_required
from django.http import JsonResponse


@login_required
def current_user(request):
    """Return the authenticated user's profile for the React frontend."""
    user = request.user
    return JsonResponse({
        'success': True,
        'data': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'full_name': user.get_full_name(),
            'display_name': user.get_full_name() or user.username or user.email,
        },
    })
