from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for
from models.inventory import db, User
from functools import wraps

auth_bp = Blueprint('auth', __name__)

def login_required(f):
    """Decorator to require user login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'error': 'Login required'}), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'GET':
        return render_template('register.html')
    
    data = request.json if request.is_json else request.form
    
    # Validate input
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')
    full_name = data.get('full_name', '').strip()
    
    # Basic required fields validation
    if not username or not email or not password:
        error = 'Username, email, and password are required'
        if request.is_json:
            return jsonify({'error': error}), 400
        return render_template('register.html', error=error)
    
    # Username validation - alphanumeric and underscore only
    if not username.replace('_', '').isalnum():
        error = 'Username can only contain letters, numbers, and underscores'
        if request.is_json:
            return jsonify({'error': error}), 400
        return render_template('register.html', error=error)
    
    # Username length validation
    if len(username) < 3 or len(username) > 30:
        error = 'Username must be between 3 and 30 characters'
        if request.is_json:
            return jsonify({'error': error}), 400
        return render_template('register.html', error=error)
    
    # Email format validation (basic)
    if '@' not in email or '.' not in email.split('@')[-1]:
        error = 'Invalid email format'
        if request.is_json:
            return jsonify({'error': error}), 400
        return render_template('register.html', error=error)
    
    # Password validation
    if len(password) < 6:
        error = 'Password must be at least 6 characters'
        if request.is_json:
            return jsonify({'error': error}), 400
        return render_template('register.html', error=error)

    if not any(not c.isalnum() for c in password):
        error = 'Password must include at least one special symbol'
        if request.is_json:
            return jsonify({'error': error}), 400
        return render_template('register.html', error=error)
    
    # Password confirmation
    if password != confirm_password:
        error = 'Passwords do not match'
        if request.is_json:
            return jsonify({'error': error}), 400
        return render_template('register.html', error=error)
    
    # Full name validation - only letters and spaces
    if full_name:
        if not all(c.isalpha() or c.isspace() for c in full_name):
            error = 'Full name can only contain letters and spaces'
            if request.is_json:
                return jsonify({'error': error}), 400
            return render_template('register.html', error=error)
        
        if len(full_name) < 2 or len(full_name) > 100:
            error = 'Full name must be between 2 and 100 characters'
            if request.is_json:
                return jsonify({'error': error}), 400
            return render_template('register.html', error=error)
        
        # Check if full name already exists
        if User.query.filter_by(full_name=full_name).first():
            error = 'This full name is already registered. Please use a different name.'
            if request.is_json:
                return jsonify({'error': error}), 400
            return render_template('register.html', error=error)
    
    # Check if username already exists (case-insensitive)
    if User.query.filter(db.func.lower(User.username) == username.lower()).first():
        error = 'Username already exists'
        if request.is_json:
            return jsonify({'error': error}), 400
        return render_template('register.html', error=error)
    
    # Check if email already exists (case-insensitive)
    if User.query.filter(db.func.lower(User.email) == email.lower()).first():
        error = 'Email already registered'
        if request.is_json:
            return jsonify({'error': error}), 400
        return render_template('register.html', error=error)
    
    # Create new user
    user = User(username=username, email=email, full_name=full_name)
    user.set_password(password)
    
    db.session.add(user)
    db.session.commit()
    
    # Auto-login after registration
    session['user_id'] = user.id
    session['username'] = user.username
    
    if request.is_json:
        return jsonify({
            'message': 'Registration successful',
            'user': user.to_dict()
        }), 201
    
    return redirect(url_for('index'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'GET':
        return render_template('login.html')
    
    data = request.json if request.is_json else request.form
    
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        error = 'Username and password are required'
        if request.is_json:
            return jsonify({'error': error}), 400
        return render_template('login.html', error=error)
    
    # Find user by username or email
    user = User.query.filter(
        (User.username == username) | (User.email == username)
    ).first()
    
    if not user or not user.check_password(password):
        error = 'Invalid username or password'
        if request.is_json:
            return jsonify({'error': error}), 401
        return render_template('login.html', error=error)
    
    # Set session
    session['user_id'] = user.id
    session['username'] = user.username
    
    if request.is_json:
        return jsonify({
            'message': 'Login successful',
            'user': user.to_dict()
        }), 200
    
    return redirect(url_for('index'))

@auth_bp.route('/logout', methods=['POST', 'GET'])
def logout():
    """User logout"""
    session.pop('user_id', None)
    session.pop('username', None)
    
    if request.is_json:
        return jsonify({'message': 'Logged out successfully'}), 200
    
    return redirect(url_for('auth.login'))

@auth_bp.route('/api/me', methods=['GET'])
@login_required
def get_current_user():
    """Get current logged-in user info"""
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify(user.to_dict()), 200

@auth_bp.route('/api/my-orders', methods=['GET'])
@login_required
def get_my_orders():
    """Get current user's orders"""
    from models.inventory import Order
    
    user_id = session['user_id']
    orders = Order.query.filter_by(user_id=user_id).order_by(Order.created_at.desc()).all()
    
    return jsonify({
        'orders': [order.to_dict() for order in orders]
    }), 200
