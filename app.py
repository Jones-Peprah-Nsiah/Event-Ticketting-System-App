import sys
import os

# Add parent directory to path so imports work from anywhere
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.insert(0, parent_dir)

# Change to src directory so relative paths work
os.chdir(current_dir)

from flask import Flask, render_template, session, redirect, url_for
from config import Config
from models.inventory import db
from routes.purchases import purchases_bp
from routes.tickets import tickets_bp
from routes.admin import admin_bp
from routes.auth import auth_bp

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config.from_object(Config)
db.init_app(app)

# Register blueprints
app.register_blueprint(purchases_bp, url_prefix='/api')
app.register_blueprint(tickets_bp, url_prefix='/api')
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(auth_bp, url_prefix='/auth')

@app.route('/')
def index():
    # Redirect to login if not authenticated
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    return render_template('index.html')

# Initialize database and create sample tickets
with app.app_context():
    # Create tables if they don't exist
    db.create_all()
    
    # Add sample tickets if none exist
    from models.inventory import Ticket, TicketType
    
    # Only add tickets if the table is empty
    if Ticket.query.count() == 0:
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
        print("✅ Database initialized with sample tickets!")
    else:
        print("✅ Database already initialized!")
    
print("✅ Application ready!")

if __name__ == '__main__':
    import webbrowser
    from threading import Timer
    
    def open_browser():
        webbrowser.open('http://127.0.0.1:5000')
    
    # Open browser after 1.5 seconds (gives Flask time to start)
    Timer(1.5, open_browser).start()
    
    app.run(debug=True)