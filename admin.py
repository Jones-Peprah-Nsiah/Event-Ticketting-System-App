
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for, make_response
from functools import wraps
from models.inventory import db, Ticket, Order, Queue, TicketType, User
from sqlalchemy import func
from datetime import datetime
import csv
from io import StringIO

admin_bp = Blueprint('admin', __name__)

# Simple admin authentication
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123'  # Change this in production!

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return jsonify({'error': 'Unauthorized. Please login.'}), 401
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Admin login page and handler"""
    if request.method == 'POST':
        data = request.json if request.is_json else request.form
        username = data.get('username')
        password = data.get('password')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            if request.is_json:
                return jsonify({'message': 'Login successful'}), 200
            return redirect(url_for('admin.dashboard'))
        
        if request.is_json:
            return jsonify({'error': 'Invalid credentials'}), 401
        return render_template('admin_login.html', error='Invalid credentials')
    
    return render_template('admin_login.html')

@admin_bp.route('/logout', methods=['POST'])
def logout():
    """Logout admin"""
    session.pop('admin_logged_in', None)
    return jsonify({'message': 'Logged out successfully'}), 200

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    """Admin dashboard showing tickets sold, revenue, and queues"""
    return render_template('admin_dashboard.html')

@admin_bp.route('/api/stats', methods=['GET'])
@admin_required
def get_stats():
    """Get statistics for admin dashboard"""
    
    # Get all tickets with sold counts
    tickets = Ticket.query.all()
    
    # Calculate total revenue from completed AND approved orders
    total_revenue = db.session.query(func.sum(Order.total_amount)).filter(
        Order.status.in_(['completed', 'approved'])
    ).scalar() or 0.0
    
    # Treat both approved and completed orders as finished since inventory is already decremented
    completed_orders = Order.query.filter(Order.status.in_(['completed', 'approved'])).count()
    
    # Get pending orders count (NEW - for approval queue)
    # Sort by VIP priority (VIP orders first, then by created date)
    pending_orders_query = Order.query.filter_by(status='pending').all()
    
    # Separate VIP and Regular orders for priority sorting
    vip_orders = []
    regular_orders = []
    mixed_orders = []
    
    for order in pending_orders_query:
        has_vip = False
        has_regular = False
        for item in order.order_items:
            if item.ticket and item.ticket.ticket_type == TicketType.VIP:
                has_vip = True
            elif item.ticket and item.ticket.ticket_type == TicketType.REGULAR:
                has_regular = True
        
        if has_vip and has_regular:
            mixed_orders.append(order)
        elif has_vip:
            vip_orders.append(order)
        else:
            regular_orders.append(order)
    
    # Sort each category by created date
    vip_orders.sort(key=lambda x: x.created_at)
    mixed_orders.sort(key=lambda x: x.created_at)
    regular_orders.sort(key=lambda x: x.created_at)
    
    # Combine with VIP priority: VIP-only orders, then mixed orders, then regular-only orders
    pending_orders = vip_orders + mixed_orders + regular_orders
    
    # Get VIP queue (includes both Queue entries and pending orders with VIP tickets)
    vip_queue_entries = Queue.query.filter_by(
        ticket_type=TicketType.VIP,
        status='waiting'
    ).order_by(Queue.joined_at).all()
    
    # Get pending orders with VIP tickets - consolidate by order
    vip_pending_orders = []
    for order in vip_orders + mixed_orders:  # Use the prioritized lists
        # Calculate total VIP quantity for this order
        vip_quantity = 0
        vip_total = 0
        for item in order.order_items:
            if item.ticket and item.ticket.ticket_type == TicketType.VIP:
                vip_quantity += item.quantity
                vip_total += item.quantity * item.price_at_purchase
        
        if vip_quantity > 0:
            vip_pending_orders.append({
                'type': 'order',
                'id': order.id,
                'user_name': order.user_name,
                'user_email': order.user_email,
                'requested_quantity': vip_quantity,
                'joined_at': order.created_at.isoformat() if order.created_at else None,
                'order_total': order.total_amount,
                'item_total': vip_total,
                'priority': 'VIP',
                'is_mixed': len(order.order_items) > 1
            })
    
    # Combine VIP queue entries and pending orders, sorted by date
    vip_queue = [{'type': 'queue', **entry.to_dict(), 'priority': 'VIP'} for entry in vip_queue_entries]
    vip_queue.extend(vip_pending_orders)
    vip_queue.sort(key=lambda x: x['joined_at'])
    
    # Get Regular queue (includes both Queue entries and pending orders with Regular tickets)
    regular_queue_entries = Queue.query.filter_by(
        ticket_type=TicketType.REGULAR,
        status='waiting'
    ).order_by(Queue.joined_at).all()
    
    # Get pending orders with Regular tickets - consolidate by order
    regular_pending_orders = []
    for order in regular_orders + mixed_orders:  # Include both regular-only and mixed orders
        # Calculate total Regular quantity for this order
        regular_quantity = 0
        regular_total = 0
        for item in order.order_items:
            if item.ticket and item.ticket.ticket_type == TicketType.REGULAR:
                regular_quantity += item.quantity
                regular_total += item.quantity * item.price_at_purchase
        
        if regular_quantity > 0:
            regular_pending_orders.append({
                'type': 'order',
                'id': order.id,
                'user_name': order.user_name,
                'user_email': order.user_email,
                'requested_quantity': regular_quantity,
                'joined_at': order.created_at.isoformat() if order.created_at else None,
                'order_total': order.total_amount,
                'item_total': regular_total,
                'priority': 'Regular',
                'is_mixed': len(order.order_items) > 1
            })
    
    # Combine Regular queue entries and pending orders, sorted by date
    regular_queue = [{'type': 'queue', **entry.to_dict(), 'priority': 'Regular'} for entry in regular_queue_entries]
    regular_queue.extend(regular_pending_orders)
    regular_queue.sort(key=lambda x: x['joined_at'])
    
    # Get recent orders (include all statuses for historical view)
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    
    return jsonify({
        'tickets': [ticket.to_dict() for ticket in tickets],
        'total_revenue': round(total_revenue, 2),
        'completed_orders': completed_orders,
        'pending_orders': [order.to_dict() for order in pending_orders],
        'pending_count': len(pending_orders),
        'vip_queue': vip_queue,
        'regular_queue': regular_queue,
        'recent_orders': [order.to_dict() for order in recent_orders]
    }), 200

@admin_bp.route('/api/tickets', methods=['POST'])
@admin_required
def update_ticket_inventory():
    """Add or update ticket inventory"""
    data = request.json
    
    if not data or 'ticket_type' not in data:
        return jsonify({'error': 'Missing ticket_type'}), 400
    
    try:
        ticket_type = TicketType[data['ticket_type'].upper()]
    except KeyError:
        return jsonify({'error': 'Invalid ticket type. Use VIP or REGULAR'}), 400
    
    # Find existing ticket or create new
    ticket = Ticket.query.filter_by(ticket_type=ticket_type).first()
    
    if ticket:
        # Update existing ticket
        if 'price' in data:
            try:
                ticket.price = float(data['price'])
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid price value'}), 400

        if 'add_quantity' in data:
            try:
                adjustment = int(data['add_quantity'])
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid quantity adjustment'}), 400

            new_quantity = ticket.available_quantity + adjustment
            if new_quantity < 0:
                return jsonify({'error': 'Available quantity cannot be negative'}), 400
            ticket.available_quantity = new_quantity

        if 'set_quantity' in data:
            try:
                new_quantity = int(data['set_quantity'])
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid quantity value'}), 400

            if new_quantity < 0:
                return jsonify({'error': 'Available quantity cannot be negative'}), 400
            ticket.available_quantity = new_quantity
    else:
        # Create new ticket
        ticket = Ticket(
            ticket_type=ticket_type,
            price=float(data.get('price', 0)),
            available_quantity=int(data.get('quantity', 0)),
            sold_quantity=0
        )
        db.session.add(ticket)
    
    db.session.commit()
    
    return jsonify({
        'message': 'Ticket inventory updated',
        'ticket': ticket.to_dict()
    }), 200

@admin_bp.route('/api/queue/<int:queue_id>/fulfill', methods=['POST'])
@admin_required
def fulfill_queue(queue_id):
    """Mark a queue entry as fulfilled"""
    queue_entry = Queue.query.get(queue_id)
    
    if not queue_entry:
        return jsonify({'error': 'Queue entry not found'}), 404
    
    queue_entry.status = 'fulfilled'
    db.session.commit()
    
    return jsonify({
        'message': 'Queue entry marked as fulfilled',
        'queue_entry': queue_entry.to_dict()
    }), 200

@admin_bp.route('/api/orders', methods=['GET'])
@admin_required
def get_all_orders():
    """Get all orders for admin review"""
    status = request.args.get('status')
    
    query = Order.query
    if status:
        query = query.filter_by(status=status)
    
    orders = query.order_by(Order.created_at.desc()).all()
    
    return jsonify({
        'orders': [order.to_dict() for order in orders]
    }), 200

@admin_bp.route('/api/orders/<int:order_id>/approve', methods=['POST'])
@admin_required
def approve_order(order_id):
    """Approve a pending order and decrement inventory. Auto-reject if sold out."""
    order = Order.query.get(order_id)
    
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    if order.status != 'pending':
        return jsonify({'error': f'Order is already {order.status}'}), 400
    
    # Validate availability - auto-reject if sold out
    for order_item in order.order_items:
        ticket = Ticket.query.get(order_item.ticket_id)
        if ticket.available_quantity < order_item.quantity:
            # Automatically reject the order - tickets sold out
            order.status = 'rejected'
            order.admin_notes = f'Auto-rejected: Insufficient {ticket.ticket_type.value} tickets available. Requested {order_item.quantity}, only {ticket.available_quantity} available.'
            db.session.commit()
            
            return jsonify({
                'error': f'Insufficient {ticket.ticket_type.value} tickets available',
                'message': 'Order has been automatically rejected due to sold out tickets.',
                'order': order.to_dict()
            }), 400
    
    # Decrement inventory and update sold count
    for order_item in order.order_items:
        ticket = Ticket.query.get(order_item.ticket_id)
        ticket.available_quantity -= order_item.quantity
        ticket.sold_quantity += order_item.quantity
        
        # Ensure available quantity never goes negative
        if ticket.available_quantity < 0:
            ticket.available_quantity = 0
    
    # Update order status
    order.status = 'approved'
    order.completed_at = datetime.utcnow()
    
    # Add admin notes if provided
    data = request.json or {}
    if data.get('notes'):
        order.admin_notes = data['notes']
    
    db.session.commit()
    
    return jsonify({
        'message': 'Order approved successfully',
        'order': order.to_dict()
    }), 200

@admin_bp.route('/api/orders/<int:order_id>/reject', methods=['POST'])
@admin_required
def reject_order(order_id):
    """Reject a pending order"""
    order = Order.query.get(order_id)
    
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    if order.status != 'pending':
        return jsonify({'error': f'Order is already {order.status}'}), 400
    
    # Update order status
    order.status = 'rejected'
    
    # Add admin notes if provided
    data = request.json or {}
    if data.get('notes'):
        order.admin_notes = data['notes']
    
    db.session.commit()
    
    return jsonify({
        'message': 'Order rejected',
        'order': order.to_dict()
    }), 200

@admin_bp.route('/export/transactions.csv', methods=['GET'])
@admin_required
def export_transactions_csv():
    """Export all transactions to CSV"""
    
    # Get all orders
    orders = Order.query.order_by(Order.created_at.desc()).all()
    
    # Create CSV in memory
    si = StringIO()
    writer = csv.writer(si)
    
    # Write header
    writer.writerow([
        'Order ID',
        'Customer Name',
        'Customer Email',
        'User ID',
        'Ticket Type',
        'Quantity',
        'Price Per Ticket',
        'Total Amount',
        'Status',
        'Order Date',
        'Completed Date',
        'Admin Notes'
    ])
    
    # Write data rows
    for order in orders:
        for item in order.order_items:
            writer.writerow([
                order.id,
                order.user_name,
                order.user_email,
                order.user_id,
                item.ticket.ticket_type.value if item.ticket else 'N/A',
                item.quantity,
                f"${item.price_at_purchase:.2f}",
                f"${order.total_amount:.2f}",
                order.status,
                order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else '',
                order.completed_at.strftime('%Y-%m-%d %H:%M:%S') if order.completed_at else '',
                order.admin_notes or ''
            ])
    
    # Create response
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=transactions.csv"
    output.headers["Content-type"] = "text/csv"
    
    return output

@admin_bp.route('/export/summary.csv', methods=['GET'])
@admin_required
def export_summary_csv():
    """Export sales summary to CSV"""
    
    # Get ticket statistics
    tickets = Ticket.query.all()
    orders = Order.query.filter(Order.status.in_(['approved', 'completed'])).all()
    
    si = StringIO()
    writer = csv.writer(si)
    
    # Sales Summary
    writer.writerow(['Sales Summary Report'])
    writer.writerow(['Generated:', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow([])
    
    # Ticket Statistics
    writer.writerow(['Ticket Type', 'Price', 'Available', 'Sold', 'Revenue'])
    for ticket in tickets:
        revenue = ticket.sold_quantity * ticket.price
        writer.writerow([
            ticket.ticket_type.value,
            f"${ticket.price:.2f}",
            ticket.available_quantity,
            ticket.sold_quantity,
            f"${revenue:.2f}"
        ])
    
    writer.writerow([])
    
    # Order Statistics
    total_revenue = sum(order.total_amount for order in orders)
    pending_count = Order.query.filter_by(status='pending').count()
    approved_count = Order.query.filter_by(status='approved').count()
    rejected_count = Order.query.filter_by(status='rejected').count()
    
    writer.writerow(['Order Statistics'])
    writer.writerow(['Total Orders', len(orders)])
    writer.writerow(['Pending Orders', pending_count])
    writer.writerow(['Approved Orders', approved_count])
    writer.writerow(['Rejected Orders', rejected_count])
    writer.writerow(['Total Revenue', f"${total_revenue:.2f}"])
    
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=sales_summary.csv"
    output.headers["Content-type"] = "text/csv"
    
    return output

@admin_bp.route('/api/reset-data', methods=['POST'])
@admin_required
def reset_data():
    """Clear all data except user accounts - resets orders, tickets, and queue"""
    try:
        # Delete all orders (this will cascade to order_items)
        Order.query.delete()
        
        # Delete all queue entries
        Queue.query.delete()
        
        # Reset ticket inventory to default values
        Ticket.query.delete()
        
        # Re-create default tickets
        vip_ticket = Ticket(
            ticket_type=TicketType.VIP,
            price=100.0,
            available_quantity=50,
            sold_quantity=0
        )
        regular_ticket = Ticket(
            ticket_type=TicketType.REGULAR,
            price=85.0,
            available_quantity=30,
            sold_quantity=0
        )
        db.session.add(vip_ticket)
        db.session.add(regular_ticket)
        
        db.session.commit()
        
        return jsonify({
            'message': 'All data cleared successfully. User accounts preserved. Tickets reset to defaults.'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to reset data: {str(e)}'}), 500

@admin_bp.route('/api/complete-reset', methods=['POST'])
@admin_required
def complete_reset():
    """COMPLETE database reset - deletes EVERYTHING including users"""
    try:
        # Delete everything
        from models.inventory import OrderItem, Inventory
        
        OrderItem.query.delete()
        Order.query.delete()
        Queue.query.delete()
        Ticket.query.delete()
        User.query.delete()
        Inventory.query.delete()
        
        # Re-create default tickets
        vip_ticket = Ticket(
            ticket_type=TicketType.VIP,
            price=100.0,
            available_quantity=50,
            sold_quantity=0
        )
        regular_ticket = Ticket(
            ticket_type=TicketType.REGULAR,
            price=85.0,
            available_quantity=100,
            sold_quantity=0
        )
        db.session.add(vip_ticket)
        db.session.add(regular_ticket)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Complete database reset successful. All data deleted. Please login again.'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to complete reset: {str(e)}'}), 500
