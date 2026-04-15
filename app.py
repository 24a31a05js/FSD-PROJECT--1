from flask import Flask, render_template, request, redirect, url_for, session, flash, g
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

from functools import wraps
app = Flask(__name__)
app.secret_key = 'secret_key_for_session_management' # Change this to a random string for security
DATABASE = 'tracker.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row # Allows accessing columns by name
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        # Create Users Table
        db.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        email TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL
                    )''')
        # Create Internships Table
        db.execute('''CREATE TABLE IF NOT EXISTS internships (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        company_name TEXT NOT NULL,
                        role TEXT NOT NULL,
                        start_date TEXT,
                        end_date TEXT,
                        status TEXT,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )''')
        # Create Experiences Table
        db.execute('''CREATE TABLE IF NOT EXISTS experiences (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        company_name TEXT NOT NULL,
                        experience_text TEXT,
                        tips TEXT,
                        FOREIGN KEY (user_id) REFERENCES users (id)
                    )''')
        # Create Admins Table
        db.execute('''CREATE TABLE IF NOT EXISTS admins (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL
                    )''')
        # --- Admin Seeding ---
        # This code ensures a default admin exists.
        # Define your new primary admin credentials here.
        new_admin_email = 'admin@tracker.com'
        if db.execute("SELECT id FROM admins WHERE username = ?", (new_admin_email,)).fetchone() is None:
            hashed_pw = generate_password_hash('AdminPass123!') # Set your new secure password
            db.execute("INSERT INTO admins (username, password) VALUES (?, ?)", (new_admin_email, hashed_pw))
        db.commit()

# Initialize DB on start
init_db()

# --- DECORATORS for route protection ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("You need to be logged in to view this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash("You must be an admin to view this page.", "error")
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def home():
    return render_template("index.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        hashed_pw = generate_password_hash(password) # Secure password hashing

        db = get_db()
        try:
            db.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)", (name, email, hashed_pw))
            db.commit()
            flash("Registration successful! Please login.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Email already exists.", "error")
    return render_template("register.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password", "error")
            
    return render_template("login.html")

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    user_id = session['user_id']

    # 1. Fetch ALL internships for Statistics (Chart & Summary Cards)
    # We need all records to show correct stats even if the table is filtered
    all_internships = db.execute("SELECT status FROM internships WHERE user_id = ?", (user_id,)).fetchall()

    stats = {
        'total': len(all_internships),
        'applied': 0,
        'ongoing': 0,
        'completed': 0,
        'selected': 0,
        'rejected': 0
    }
    
    for row in all_internships:
        if row['status']:
            # Convert to lowercase to match keys (e.g., "Applied" -> "applied")
            s = row['status'].lower()
            if s in stats:
                stats[s] += 1

    # 2. Fetch FILTERED internships for the Table
    query = "SELECT * FROM internships WHERE user_id = ?"
    params = [user_id]

    # Search Logic
    search = request.args.get('search')
    if search:
        query += " AND (company_name LIKE ? OR role LIKE ?)"
        # Add wildcards % for partial matching
        params.extend([f'%{search}%', f'%{search}%'])

    # Filter Logic
    status_filter = request.args.get('status_filter')
    if status_filter and status_filter != 'All':
        query += " AND status = ?"
        params.append(status_filter)

    query += " ORDER BY id DESC"
    
    internships = db.execute(query, params).fetchall()

    return render_template("dashboard.html", 
                           internships=internships, 
                           name=session['user_name'], 
                           stats=stats,
                           search=search,
                           status_filter=status_filter)

@app.route('/add_internship', methods=['GET', 'POST'])
@login_required
def add_internship():
    if request.method == 'POST':
        company = request.form['company']
        role = request.form['role']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        status = request.form['status']
        
        db = get_db()
        db.execute("INSERT INTO internships (user_id, company_name, role, start_date, end_date, status) VALUES (?, ?, ?, ?, ?, ?)",
                   (session['user_id'], company, role, start_date, end_date, status))
        db.commit()
        flash("Internship added successfully!", "success")
        return redirect(url_for('dashboard'))
        
    return render_template("add_internship.html")

@app.route('/edit_internship/<int:internship_id>', methods=['GET', 'POST'])
@login_required
def edit_internship(internship_id):
    db = get_db()
    # Ensure the internship belongs to the current user
    internship = db.execute("SELECT * FROM internships WHERE id = ? AND user_id = ?", 
                            (internship_id, session['user_id'])).fetchone()

    if internship is None:
        flash("Internship not found or you don't have permission to edit it.", "error")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # Update logic
        company = request.form['company']
        role = request.form['role']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        status = request.form['status']
        
        db.execute("""UPDATE internships SET 
                      company_name = ?, role = ?, start_date = ?, end_date = ?, status = ?
                      WHERE id = ?""",
                   (company, role, start_date, end_date, status, internship_id))
        db.commit()
        flash("Internship updated successfully!", "success")
        return redirect(url_for('dashboard'))

    # GET request: show the form pre-filled with data
    return render_template("edit_internship.html", internship=internship)

@app.route('/delete_internship/<int:internship_id>')
@login_required
def delete_internship(internship_id):
    db = get_db()
    # Ensure the internship belongs to the current user before deleting
    internship = db.execute("SELECT id FROM internships WHERE id = ? AND user_id = ?", (internship_id, session['user_id'])).fetchone()

    if internship:
        db.execute("DELETE FROM internships WHERE id = ?", (internship_id,))
        db.commit()
        flash("Internship deleted successfully.", "success")
    else:
        flash("Internship not found or you don't have permission to delete it.", "error")
        
    return redirect(url_for('dashboard'))

@app.route('/experiences')
def experiences():
    if 'user_id' not in session and not session.get('admin_logged_in'):
        return redirect(url_for('login'))
    
    db = get_db()
    # Join experiences with users to get the author's name
    all_experiences = db.execute("""
        SELECT e.id, e.company_name, e.experience_text, e.tips, u.name as author_name
        FROM experiences e JOIN users u ON e.user_id = u.id
        ORDER BY e.id DESC
    """).fetchall()
    
    return render_template("experiences.html", experiences=all_experiences, is_admin=session.get('admin_logged_in'))

@app.route('/add_experience', methods=['GET', 'POST'])
@login_required
def add_experience():
    if request.method == 'POST':
        company = request.form['company']
        experience_text = request.form['experience_text']
        tips = request.form['tips']
        
        db = get_db()
        db.execute("INSERT INTO experiences (user_id, company_name, experience_text, tips) VALUES (?, ?, ?, ?)",
                   (session['user_id'], company, experience_text, tips))
        db.commit()
        flash("Your experience has been shared successfully!", "success")
        return redirect(url_for('experiences'))
    
    return render_template("add_experience.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- ADMIN ROUTES ---

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        db = get_db()
        admin = db.execute("SELECT * FROM admins WHERE username = ?", (email,)).fetchone()
        
        if admin and check_password_hash(admin['password'], password):
            session['admin_logged_in'] = True
            session['admin_username'] = admin['username']
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid admin credentials", "error")
            
    return render_template("admin_login.html")

@app.route('/admin/register', methods=['GET', 'POST'])
@admin_required
def admin_register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("admin_register.html")

        hashed_pw = generate_password_hash(password)
        db = get_db()
        try:
            # The 'username' column in the 'admins' table is used for the email
            db.execute("INSERT INTO admins (username, password) VALUES (?, ?)", (email, hashed_pw))
            db.commit()
            flash(f"New admin account '{email}' created successfully!", "success")
            return redirect(url_for('admin_dashboard'))
        except sqlite3.IntegrityError:
            flash("An admin with that email already exists.", "error")
    return render_template("admin_register.html")

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db()
    
    # 1. Fetch Statistics
    total_students = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_internships = db.execute("SELECT COUNT(*) FROM internships").fetchone()[0]
    
    stats = {
        'total_students': total_students,
        'total_internships': total_internships,
        'applied': 0,
        'ongoing': 0,
        'completed': 0,
        'selected': 0,
        'rejected': 0
    }
    
    # Count by status
    status_counts = db.execute("SELECT status, COUNT(*) FROM internships GROUP BY status").fetchall()
    for row in status_counts:
        if row['status']:
            key = row['status'].lower()
            if key in stats:
                stats[key] = row[1]

    return render_template("admin_dashboard.html", stats=stats)

@app.route('/admin/internships')
@admin_required
def admin_internships():
    db = get_db()
    # Fetch All Internships with Student Names
    all_internships = db.execute("""
        SELECT i.*, u.name as student_name 
        FROM internships i 
        JOIN users u ON i.user_id = u.id 
        ORDER BY i.id DESC
    """).fetchall()

    return render_template("admin_internships.html", internships=all_internships)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/delete_experience/<int:experience_id>')
@admin_required
def admin_delete_experience(experience_id):
    db = get_db()
    db.execute("DELETE FROM experiences WHERE id = ?", (experience_id,))
    db.commit()
    flash("Experience deleted successfully.", "success")
    return redirect(url_for('experiences'))

@app.route('/admin/update_status/<int:internship_id>', methods=['POST'])
@admin_required
def admin_update_status(internship_id):
    new_status = request.form['status']
    db = get_db()
    db.execute("UPDATE internships SET status = ? WHERE id = ?", (new_status, internship_id))
    db.commit()
    flash("Internship status updated.", "success")
    return redirect(url_for('admin_internships'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user_type = request.form['user_type']
        
        db = get_db()
        user = None
        if user_type == 'student':
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        elif user_type == 'admin':
            # Admins table uses 'username' column for email
            user = db.execute("SELECT * FROM admins WHERE username = ?", (email,)).fetchone()

        if user:
            session['reset_email'] = email
            session['reset_type'] = user_type
            return redirect(url_for('reset_password'))
        else:
            flash("Email not found.", "error")
            
    return render_template("forgot_password.html")

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if 'reset_email' not in session:
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        password = request.form['password']
        hashed_pw = generate_password_hash(password)
        email = session['reset_email']
        user_type = session['reset_type']
        
        db = get_db()
        if user_type == 'student':
            db.execute("UPDATE users SET password = ? WHERE email = ?", (hashed_pw, email))
        elif user_type == 'admin':
            db.execute("UPDATE admins SET password = ? WHERE username = ?", (hashed_pw, email))
        db.commit()
        
        session.pop('reset_email', None)
        session.pop('reset_type', None)
        flash("Password reset successful. Please login.", "success")
        
        return redirect(url_for('login') if user_type == 'student' else url_for('admin_login'))
            
    return render_template("reset_password.html")

if __name__ == "__main__":
    app.run(debug=True)
