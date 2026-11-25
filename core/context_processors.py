from django.conf import settings


def site(request):
    """The site's name for every page as brand_name. (Django's sign-in view already uses site_name.)"""
    return {"brand_name": settings.SITE_NAME}
