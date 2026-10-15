"""Server-side, default-deny permissions shared by routes and templates."""
from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def can(permission, obj=None, user=None):
    user = current_user if user is None else user
    if not user.is_authenticated or not user.is_active:
        return False
    if permission not in {
        'manage_system', 'manage_competitions', 'create_owner', 'create_jockey',
        'create_horse', 'manage_horse', 'manage_owner', 'manage_jockey', 'account',
    }:
        return False
    if user.role == 'ROOT':
        return True
    if permission == 'account':
        return True
    if permission == 'manage_competitions':
        return user.role == 'ADMIN'
    if permission == 'create_horse':
        return user.role == 'OWNER' and user.owner_id is not None
    if permission == 'manage_horse':
        return user.role == 'OWNER' and obj is not None and obj.owner_id == user.owner_id
    if permission == 'manage_owner':
        return user.role == 'OWNER' and obj is not None and obj.id == user.owner_id
    if permission == 'manage_jockey':
        return user.role == 'JOCKEY' and obj is not None and obj.id == user.jockey_id
    return False


def permission_required(permission):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not can(permission):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
