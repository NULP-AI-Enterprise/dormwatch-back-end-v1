"""Resource capabilities shared by API reads and mutations."""
def is_resource_admin(user):
    profile = getattr(user, "profile", None)
    role = getattr(getattr(profile, "role", None), "role_name", "").lower()
    return bool(user.is_authenticated and (user.is_staff or role in ("admin", "адміністратор")))


def resource_admin_building(user):
    profile = getattr(user, "profile", None)
    if not profile:
        return None
    return profile.building_id or (profile.place.building_id if profile.place else None)


def can_manage_complaint_resources(user, complaint):
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    if is_resource_admin(user):
        building_id = resource_admin_building(user)
        return bool(building_id and complaint.place and complaint.place.building_id == building_id)
    profile = getattr(user, "profile", None)
    role = getattr(getattr(profile, "role", None), "role_name", "").lower()
    return bool(profile and role in ("worker", "працівник") and complaint.worker
                and complaint.worker.account_id == profile.pk)


def can_read_complaint_resources(user, complaint):
    if can_manage_complaint_resources(user, complaint):
        return True
    profile = getattr(user, "profile", None)
    if not profile:
        return False
    if complaint.user_id == profile.pk:
        return True
    worker = getattr(profile, "worker", None)
    return bool(worker and complaint.events.filter(worker=worker).exists())
