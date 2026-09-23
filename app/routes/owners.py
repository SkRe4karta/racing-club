from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Owner

owners_bp = Blueprint('owners', __name__)

@owners_bp.route('/')
def list_owners():
    owners = Owner.query.order_by(Owner.full_name.asc()).all()
    return render_template('owners/list.html', owners=owners)

@owners_bp.route('/add', methods=['GET', 'POST'])
def add_owner():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        address = request.form.get('address', '').strip()
        phone = request.form.get('phone', '').strip()

        if not full_name:
            flash("Поле «ФИО владельца» обязательно для заполнения.", "danger")
            return render_template('owners/form.html', full_name=full_name, address=address, phone=phone)

        owner = Owner(full_name=full_name, address=address or None, phone=phone or None)
        db.session.add(owner)
        db.session.commit()
        flash(f"Владелец «{owner.full_name}» успешно добавлен.", "success")
        return redirect(url_for('owners.list_owners'))

    return render_template('owners/form.html')

@owners_bp.route('/<int:owner_id>')
def detail_owner(owner_id):
    owner = db.session.get(Owner, owner_id)
    if not owner:
        flash("Владелец не найден.", "warning")
        return redirect(url_for('owners.list_owners'))
    return render_template('owners/detail.html', owner=owner)
