from .models import Notification, get_profile


def unread_count(request):
    if not request.user.is_authenticated:
        return {}
    return {
        "unread_count": Notification.objects.filter(
            user=request.user, read_at__isnull=True
        ).count(),
        "email_verified": get_profile(request.user).email_verified,
        "has_email": bool(request.user.email),
    }