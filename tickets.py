from flask import Blueprint, request, jsonify, session, render_template_string
from models.inventory import db, Ticket, Order, OrderItem, Queue, TicketType, User
from datetime import datetime
from functools import wraps

tickets_bp = Blueprint('tickets', __name__)

def login_required(f):
    """Decorator to require user login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Login required'}), 401
        return f(*args, **kwargs)
    return decorated_function

@tickets_bp.route('/tickets', methods=['GET'])
def get_tickets():
    """Get all available tickets"""
    tickets = Ticket.query.all()
    return jsonify({
        'tickets': [ticket.to_dict() for ticket in tickets]
    }), 200

@tickets_bp.route('/orders', methods=['POST'])
@login_required
def create_order():
    """
    Create a new order with selected tickets.
    Max 5 tickets combined (VIP + Regular).
    Order status is 'pending' - awaiting admin approval.
    """
    data = request.json
    user_id = session.get('user_id')
    
    # Get user info
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Guard against multiple open orders per user to keep admin queue clean
    existing_order = Order.query.filter(
        Order.user_id == user_id,
        Order.status.in_(['pending', 'approved', 'completed'])
    ).order_by(Order.created_at.desc()).first()

    if existing_order:
        if existing_order.status == 'completed':
            return jsonify({
                'error': 'You have already completed an order. Each user is limited to one completed purchase.',
                'order_id': existing_order.id,
                'order_status': existing_order.status
            }), 409

        return jsonify({
            'error': 'You already have an active order awaiting processing. Please wait for the admin to review it before placing a new one.',
            'order_id': existing_order.id,
            'order_status': existing_order.status
        }), 409

    # Validate input
    if not data or 'items' not in data:
        return jsonify({'error': 'Missing required field: items'}), 400
    
    items = data['items']  # Expected format: [{'ticket_id': 1, 'quantity': 2}, ...]
    
    # DEBUG: Log what items we received
    print(f"DEBUG - Received items: {items}")
    
    # Validate total quantity (ensure at least one ticket requested)
    total_quantity = sum(item.get('quantity', 0) for item in items)
    if total_quantity < 1:
        return jsonify({'error': 'At least 1 ticket required'}), 400
    
    # Create order - status is 'pending' by default
    order = Order(
        user_id=user_id,
        user_name=user.full_name or user.username,
        user_email=user.email,
        status='pending'  # Admin must approve
    )
    
    total_amount = 0.0
    aggregated_items = {}
    
    # Add order items and validate availability
    for item in items:
        ticket_id = item.get('ticket_id')
        quantity = item.get('quantity', 0)
        
        if quantity < 1:
            continue
        
        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            return jsonify({'error': f'Ticket ID {ticket_id} not found'}), 404
        
        if ticket_id not in aggregated_items:
            aggregated_items[ticket_id] = {
                'ticket': ticket,
                'quantity': 0
            }
        aggregated_items[ticket_id]['quantity'] += quantity
        
        # Ensure combined quantity doesn't exceed availability
        if aggregated_items[ticket_id]['quantity'] > ticket.available_quantity:
            return jsonify({'error': f'Not enough {ticket.ticket_type.value} tickets available'}), 400
    
    if not aggregated_items:
        return jsonify({'error': 'At least 1 ticket required'}), 400
    
    # Prepare flattened order items list and total amount after aggregation
    order_items_data = []
    for ticket_id, info in aggregated_items.items():
        order_items_data.append({
            'ticket_id': ticket_id,
            'quantity': info['quantity'],
            'price': info['ticket'].price
        })
        total_amount += info['ticket'].price * info['quantity']
    
    order.total_amount = total_amount
    
    # Add order to session
    db.session.add(order)
    db.session.commit()
    
    # Get the order ID
    order_id = order.id
    
    # Now create OrderItems for this order
    for item_data in order_items_data:
        new_item = OrderItem(
            order_id=order_id,
            ticket_id=item_data['ticket_id'],
            quantity=item_data['quantity'],
            price_at_purchase=item_data['price']
        )
        db.session.add(new_item)
    
    # DEBUG: Log what we're about to commit
    print(f"DEBUG - Creating {len(order_items_data)} items for order #{order_id}")
    
    db.session.commit()
    
    # Reload the order fresh from database
    final_order = db.session.query(Order).get(order_id)
    print(f"DEBUG - Final check: Order #{order_id} has {len(final_order.order_items)} items")
    print(f"DEBUG - Items: {[(item.ticket_id, item.quantity) for item in final_order.order_items]}")
    
    return jsonify({
        'message': 'Ticket request submitted successfully. Awaiting admin approval.',
        'order': final_order.to_dict()
    }), 201

@tickets_bp.route('/orders/<int:order_id>/complete', methods=['POST'])
def complete_order(order_id):
    """
    Complete the purchase and decrement ticket inventory.
    This is when the actual purchase happens.
    """
    order = Order.query.get(order_id)
    
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    if order.status == 'completed':
        return jsonify({'error': 'Order already completed'}), 400
    
    if order.status == 'cancelled':
        return jsonify({'error': 'Order was cancelled'}), 400
    
    # Validate availability again (in case inventory changed)
    for order_item in order.order_items:
        ticket = Ticket.query.get(order_item.ticket_id)
        if ticket.available_quantity < order_item.quantity:
            return jsonify({
                'error': f'Insufficient {ticket.ticket_type.value} tickets available'
            }), 400
    
    # Decrement inventory and update sold count
    for order_item in order.order_items:
        ticket = Ticket.query.get(order_item.ticket_id)
        ticket.available_quantity -= order_item.quantity
        ticket.sold_quantity += order_item.quantity
    
    # Update order status
    order.status = 'completed'
    order.completed_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({
        'message': 'Purchase completed successfully',
        'order': order.to_dict()
    }), 200

@tickets_bp.route('/orders/<int:order_id>', methods=['GET'])
@login_required
def get_order(order_id):
    """Get order details"""
    order = Order.query.get(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    # Ensure user can only view their own orders
    if order.user_id != session.get('user_id'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    return jsonify(order.to_dict()), 200

@tickets_bp.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
def cancel_order(order_id):
    """
    Cancel an approved order and refund tickets to inventory.
    Only approved or completed orders can be cancelled for refund.
    """
    order = Order.query.get(order_id)
    
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    # Ensure user can only cancel their own orders
    if order.user_id != session.get('user_id'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Only allow cancellation of approved or completed orders
    if order.status not in ['approved', 'completed']:
        return jsonify({'error': f'Cannot cancel {order.status} orders. Only approved/completed orders can be cancelled for refund.'}), 400
    
    # Return tickets to inventory
    for order_item in order.order_items:
        ticket = Ticket.query.get(order_item.ticket_id)
        ticket.available_quantity += order_item.quantity
        ticket.sold_quantity -= order_item.quantity
        
        # Ensure sold quantity never goes negative
        if ticket.sold_quantity < 0:
            ticket.sold_quantity = 0
    
    # Update order status to cancelled
    order.status = 'cancelled'
    order.admin_notes = (order.admin_notes or '') + f'\n[User cancelled for refund on {datetime.utcnow().strftime("%Y-%m-%d %H:%M")}]'
    
    db.session.commit()
    
    return jsonify({
        'message': 'Order cancelled successfully. Tickets have been returned to inventory and refund will be processed.',
        'order': order.to_dict()
    }), 200

@tickets_bp.route('/orders/<int:order_id>/receipt', methods=['GET'])
@login_required
def get_receipt(order_id):
    """Generate and display receipt for approved/completed orders"""
    order = Order.query.get(order_id)
    
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    # Ensure user can only view their own receipts
    if order.user_id != session.get('user_id'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Only show receipts for approved or completed orders
    if order.status not in ['approved', 'completed']:
        return jsonify({'error': f'Receipt not available for {order.status} orders'}), 400
    
    receipt_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Receipt - Order #{order.id}</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{
                background-color: #f8f9fa;
                padding: 20px;
            }}
            .receipt {{
                max-width: 800px;
                margin: 0 auto;
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 0 20px rgba(0,0,0,0.1);
            }}
            .receipt-header {{
                text-align: center;
                border-bottom: 3px solid #007bff;
                padding-bottom: 20px;
                margin-bottom: 30px;
            }}
            .receipt-details {{
                margin-bottom: 30px;
            }}
            .receipt-table {{
                margin-bottom: 30px;
            }}
            .receipt-footer {{
                border-top: 2px solid #dee2e6;
                padding-top: 20px;
                text-align: center;
                color: #6c757d;
            }}
            @media print {{
                body {{
                    background: white;
                    padding: 0;
                }}
                .receipt {{
                    box-shadow: none;
                    padding: 20px;
                }}
                .no-print {{
                    display: none;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="receipt">
            <div class="receipt-header">
                <h1>🎫 Event Ticket Receipt</h1>
                <p class="text-muted mb-0">Official Purchase Confirmation</p>
            </div>
            
            <div class="receipt-details">
                <div class="row">
                    <div class="col-md-6">
                        <h5>Order Information</h5>
                        <p class="mb-1"><strong>Order Number:</strong> #{order.id}</p>
                        <p class="mb-1"><strong>Order Date:</strong> {order.created_at.strftime('%B %d, %Y at %I:%M %p') if order.created_at else 'N/A'}</p>
                        <p class="mb-1"><strong>Approved Date:</strong> {order.completed_at.strftime('%B %d, %Y at %I:%M %p') if order.completed_at else 'N/A'}</p>
                        <p class="mb-1"><strong>Status:</strong> <span class="badge bg-success">{order.status.upper()}</span></p>
                    </div>
                    <div class="col-md-6">
                        <h5>Customer Information</h5>
                        <p class="mb-1"><strong>Name:</strong> {order.user_name}</p>
                        <p class="mb-1"><strong>Email:</strong> {order.user_email}</p>
                        <p class="mb-1"><strong>Customer ID:</strong> {order.user_id}</p>
                    </div>
                </div>
            </div>
            
            <div class="receipt-table">
                <h5>Ticket Details</h5>
                <table class="table table-bordered">
                    <thead class="table-light">
                        <tr>
                            <th>Ticket Type</th>
                            <th class="text-center">Quantity</th>
                            <th class="text-end">Unit Price</th>
                            <th class="text-end">Subtotal</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f'''
                        <tr>
                            <td>{item.ticket.ticket_type.value if item.ticket else 'N/A'}</td>
                            <td class="text-center">{item.quantity}</td>
                            <td class="text-end">${item.price_at_purchase:.2f}</td>
                            <td class="text-end">${(item.quantity * item.price_at_purchase):.2f}</td>
                        </tr>
                        ''' for item in order.order_items])}
                    </tbody>
                    <tfoot>
                        <tr class="table-light">
                            <td colspan="3" class="text-end"><strong>Total Amount:</strong></td>
                            <td class="text-end"><strong>${order.total_amount:.2f}</strong></td>
                        </tr>
                    </tfoot>
                </table>
            </div>
            
            {f'<div class="alert alert-info"><strong>Note:</strong> {order.admin_notes}</div>' if order.admin_notes else ''}
            
            <div class="receipt-footer">
                <p class="mb-2"><strong>Thank you for your purchase!</strong></p>
                <p class="mb-0">This is an official receipt for your ticket order.</p>
                <p class="text-muted">Please present this receipt at the event venue.</p>
            </div>
            
            <div class="text-center mt-4 no-print">
                <button class="btn btn-primary me-2" onclick="window.print()">🖨️ Print Receipt</button>
                <a href="/" class="btn btn-secondary">← Back to Home</a>
            </div>
        </div>
    </body>
    </html>
    """
    
    return render_template_string(receipt_html)

@tickets_bp.route('/queue', methods=['POST'])
def join_queue():
    """Add user to waiting queue when tickets are sold out"""
    data = request.json
    
    if not data or 'user_name' not in data or 'user_email' not in data or 'ticket_type' not in data or 'quantity' not in data:
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        ticket_type = TicketType[data['ticket_type'].upper()]
    except KeyError:
        return jsonify({'error': 'Invalid ticket type. Use VIP or REGULAR'}), 400
    
    queue_entry = Queue(
        user_name=data['user_name'],
        user_email=data['user_email'],
        ticket_type=ticket_type,
        requested_quantity=data['quantity']
    )
    
    db.session.add(queue_entry)
    db.session.commit()
    
    return jsonify({
        'message': 'Added to queue successfully',
        'queue_entry': queue_entry.to_dict()
    }), 201
