from flask import Blueprint, request, jsonify
from models.inventory import db, Inventory

purchases_bp = Blueprint('purchases', __name__)

@purchases_bp.route('/purchase/<int:item_id>', methods=['POST'])
def purchase_item(item_id):
    """Legacy purchase endpoint for backward compatibility"""
    item = Inventory.query.get(item_id)
    if item and item.quantity > 0:
        item.quantity -= 1
        db.session.commit()
        return jsonify({'message': 'Purchase successful', 'item_id': item_id, 'remaining_quantity': item.quantity}), 200
    return jsonify({'message': 'Item not available or out of stock'}), 400

@purchases_bp.route('/inventory', methods=['GET'])
def get_inventory():
    """Get all inventory items"""
    items = Inventory.get_inventory()
    return jsonify({
        'inventory': [{'id': item.id, 'item_name': item.item_name, 'quantity': item.quantity} for item in items]
    }), 200