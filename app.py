import base64
import os
import random
import sqlite3
import time
import math
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db_connection():
    conn = sqlite3.connect('coffee_sparks.db')
    conn.row_factory = sqlite3.Row
    return conn

def haversine_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2): return 999
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(d_lon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def setup_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            real_name TEXT NOT NULL,
            nickname TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            coffee_shop TEXT,
            bio TEXT,
            profile_image TEXT,
            caffeine_status TEXT DEFAULT 'Craving an iced latte ☕',
            audio_intro TEXT,
            last_lat REAL,
            last_lng REAL
        )
    ''')
    
    migration_cols = [
        ('caffeine_status', "TEXT DEFAULT 'Craving an iced latte ☕'"), 
        ('audio_intro', 'TEXT'),
        ('last_lat', 'REAL'),
        ('last_lng', 'REAL')
    ]
    for col, col_type in migration_cols:
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col} {col_type}')
        except sqlite3.OperationalError:
            pass

    # Add Security Questions to Users Table
    sq_cols = [
        ('sq_teacher', 'TEXT'),
        ('sq_dog', 'TEXT'),
        ('sq_food', 'TEXT'),
        ('sq_phone', 'TEXT'),
        ('sq_date', 'TEXT')
    ]
    for col, col_type in sq_cols:
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col} {col_type}')
        except sqlite3.OperationalError:
            pass

    # 2. User Photos Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            image_filename TEXT NOT NULL,
            caption TEXT,
            is_private INTEGER DEFAULT 1,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    try:
        cursor.execute('ALTER TABLE user_photos ADD COLUMN is_private INTEGER DEFAULT 1')
    except sqlite3.OperationalError:
        pass

    # 3. User Likes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_user_id, to_user_id),
            FOREIGN KEY(from_user_id) REFERENCES users(id),
            FOREIGN KEY(to_user_id) REFERENCES users(id)
        )
    ''')

    # 4. Date Invites Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS date_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            cafe_name TEXT NOT NULL,
            meet_time TEXT NOT NULL,
            message TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(from_user_id) REFERENCES users(id),
            FOREIGN KEY(to_user_id) REFERENCES users(id)
        )
    ''')
    try:
        cursor.execute('ALTER TABLE date_invites ADD COLUMN message TEXT')
    except sqlite3.OperationalError:
        pass

    # 5. Private Moments (Secret Brews) Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS private_moments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            image_base64 TEXT,
            caption TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 6. Messages Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(from_user_id) REFERENCES users(id),
            FOREIGN KEY(to_user_id) REFERENCES users(id)
        )
    ''')

    # 7. Secret Access Permissions Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS secret_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            viewer_id INTEGER NOT NULL,
            moment_id INTEGER NOT NULL,
            UNIQUE(owner_id, viewer_id, moment_id)
        )
    ''')

    # Profile Wall Comments Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS profile_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_user_id INTEGER NOT NULL,
            commenter_user_id INTEGER NOT NULL,
            commenter_name TEXT NOT NULL,
            commenter_image TEXT,
            comment TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(profile_user_id) REFERENCES users(id),
            FOREIGN KEY(commenter_user_id) REFERENCES users(id)
        )
    ''')

    # 8. OTP Verification Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS otp_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            expires_at DATETIME NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

# Run table setup globally on startup
setup_database()

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "success", "message": "Coffee Sparks server is awake!"})

# Configure with your real DriveElite credentials
SMTP_EMAIL = "contact@driveelite.ph" 
SMTP_APP_PASSWORD = "chcskxti6hc2d7ao"

@app.route('/request_otp', methods=['POST'])
def request_otp():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400

    code = str(random.randint(100000, 999999))
    
    # Format datetime as a strict string so SQLite accepts it safely
    expires_at_str = (datetime.utcnow() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM otp_codes WHERE email = ?', (email,))
        conn.execute('''
            INSERT INTO otp_codes (email, code, expires_at)
            VALUES (?, ?, ?)
        ''', (email, code, expires_at_str))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500
    conn.close()

    # --- EMAIL SENDING LOGIC ---
    try:
        msg = MIMEText(f"Your Let's Have Coffee login code is: {code}\n\nIt expires in 5 minutes. ☕")
        msg['Subject'] = 'Your LHC Login Code'
        msg['From'] = f"Let's Have Coffee <{SMTP_EMAIL}>"
        msg['To'] = email

        # FIXED: Added 'timeout=10' so the worker doesn't freeze and crash!
        with smtplib.SMTP_SSL('mail.driveelite.ph', 465, timeout=10) as server:
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
            server.send_message(msg)
            
    except Exception as e:
        print(f"Error details: {str(e)}")
        return jsonify({"status": "error", "message": f"Email error: {str(e)}"}), 500

    return jsonify({"status": "success", "message": "OTP Sent!"}), 200

@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()

    conn = get_db_connection()
    otp_record = conn.execute('SELECT * FROM otp_codes WHERE email = ? AND code = ?', (email, code)).fetchone()

    if not otp_record:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid code. Try again."}), 400

    # Parse the strict string format back into a datetime object
    expires_at = datetime.strptime(otp_record['expires_at'], "%Y-%m-%d %H:%M:%S")
    if expires_at < datetime.utcnow():
        conn.close()
        return jsonify({"status": "error", "message": "Code expired. Request a new one."}), 400

    conn.execute('DELETE FROM otp_codes WHERE email = ?', (email,))
    user = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    conn.commit()
    conn.close()

    if user:
        return jsonify({"status": "success", "is_new_user": False, "user_id": user['id']}), 200
    else:
        return jsonify({"status": "success", "is_new_user": True}), 200

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    lat = data.get('lat')
    lng = data.get('lng')

    if not email or not password:
        return jsonify({"status": "error", "message": "Missing credentials"}), 400

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    
    if user and check_password_hash(user['password'], password):
        if lat is not None and lng is not None:
            conn.execute('UPDATE users SET last_lat = ?, last_lng = ? WHERE id = ?', (lat, lng, user['id']))
            conn.commit()
        conn.close()
        return jsonify({"status": "success", "user_id": user['id']}), 200
    else:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid email or password"}), 401

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email', f"user_{int(time.time())}@coffee.com").strip().lower()
    raw_password = data.get('password', 'temporarypassword')
    hashed_password = generate_password_hash(raw_password)
    real_name = data.get('real_name', 'Coffee Lover')
    nickname = data.get('nickname', real_name)
    age = int(data.get('age', 18))
    gender = data.get('gender', 'Man')
    coffee_shop = data.get('coffee_shop', 'Local Cafe')
    bio = data.get('bio', '')

    # Security Questions extraction
    sq_teacher = data.get('sq_teacher', '').strip().lower()
    sq_dog = data.get('sq_dog', '').strip().lower()
    sq_food = data.get('sq_food', '').strip().lower()
    sq_phone = data.get('sq_phone', '').strip().lower()
    sq_date = data.get('sq_date', '').strip().lower()
    
    avatar_filename = None
    image_b64 = data.get('image_base64')
    if image_b64:
        try:
            avatar_filename = f"avatar_{int(time.time())}.jpg"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], avatar_filename)
            with open(filepath, "wb") as fh:
                fh.write(base64.b64decode(image_b64))
        except Exception as err:
            print(f"Error saving avatar: {err}")
            avatar_filename = None

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (email, password, real_name, nickname, age, gender, coffee_shop, bio, profile_image, sq_teacher, sq_dog, sq_food, sq_phone, sq_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (email, hashed_password, real_name, nickname, age, gender, coffee_shop, bio, avatar_filename, sq_teacher, sq_dog, sq_food, sq_phone, sq_date))
        conn.commit()
        new_user_id = cursor.lastrowid
        return jsonify({"status": "success", "message": "Profile registered!", "user_id": new_user_id}), 201
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "Email already exists."}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/recover_account', methods=['POST'])
def recover_account():
    data = request.get_json(force=True, silent=True) or {}
    recovery_type = data.get('type')
    
    ans_teacher = data.get('sq_teacher', '').strip().lower()
    ans_dog = data.get('sq_dog', '').strip().lower()
    ans_food = data.get('sq_food', '').strip().lower()
    ans_phone = data.get('sq_phone', '').strip().lower()
    ans_date = data.get('sq_date', '').strip().lower()

    conn = get_db_connection()
    
    if recovery_type == 'email':
        nickname = data.get('nickname', '').strip()
        user = conn.execute('''
            SELECT email FROM users 
            WHERE nickname = ? AND sq_teacher = ? AND sq_dog = ? AND sq_food = ? AND sq_phone = ? AND sq_date = ?
        ''', (nickname, ans_teacher, ans_dog, ans_food, ans_phone, ans_date)).fetchone()
        
        conn.close()
        if user:
            return jsonify({"status": "success", "message": f"Your email is: {user['email']}"}), 200
        return jsonify({"status": "error", "message": "Answers do not match any records."}), 404

    elif recovery_type == 'password':
        email = data.get('email', '').strip().lower()
        new_password = data.get('new_password', '').strip()
        
        user = conn.execute('''
            SELECT id FROM users 
            WHERE email = ? AND sq_teacher = ? AND sq_dog = ? AND sq_food = ? AND sq_phone = ? AND sq_date = ?
        ''', (email, ans_teacher, ans_dog, ans_food, ans_phone, ans_date)).fetchone()
        
        if user:
            hashed_pw = generate_password_hash(new_password)
            conn.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_pw, user['id']))
            conn.commit()
            conn.close()
            return jsonify({"status": "success", "message": "Password successfully reset! You can now log in."}), 200
        
        conn.close()
        return jsonify({"status": "error", "message": "Answers do not match our records for that email."}), 404

    return jsonify({"status": "error", "message": "Invalid request type"}), 400


@app.route('/upload_private_moment', methods=['POST'])
def upload_private_moment():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get('user_id')
    image_base64 = data.get('image_base64')
    caption = data.get('caption', '')
    
    if not user_id or not image_base64:
        return jsonify({"status": "error", "message": "Missing user_id or image"}), 400
        
    filename = secure_filename(f"moment_{user_id}_{int(time.time())}.jpg")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    try:
        with open(filepath, "wb") as fh:
            fh.write(base64.b64decode(image_base64))
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error saving file: {e}"}), 500

    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO private_moments (user_id, image_base64, caption) VALUES (?, ?, ?)',
                     (user_id, filename, caption))
        conn.commit()
        return jsonify({"status": "success", "message": "Private moment saved successfully!"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/get_secret_moments/<int:viewer_id>/<int:target_id>', methods=['GET'])
def get_secret_moments(viewer_id, target_id):
    conn = get_db_connection()
    rows = conn.execute('SELECT id, image_base64, caption, timestamp FROM private_moments WHERE user_id = ? ORDER BY id DESC', (target_id,)).fetchall()
    
    moments = []
    for r in rows:
        moment_id = r['id']
        filename = r['image_base64'] or ''
        img_url = f"{request.host_url}uploads/{filename}" if filename else ""
        
        unlocked = True
        if viewer_id != target_id:
            access = conn.execute('''
                SELECT 1 FROM secret_access WHERE owner_id = ? AND viewer_id = ? AND moment_id = ?
            ''', (target_id, viewer_id, moment_id)).fetchone()
            unlocked = access is not None

        moments.append({
            "id": moment_id,
            "image": img_url,
            "caption": r['caption'] or "",
            "unlocked": unlocked,
            "timestamp": r['timestamp']
        })
        
    conn.close()
    return jsonify({"status": "success", "moments": moments}), 200

@app.route('/grant_secret_access', methods=['POST'])
def grant_secret_access():
    data = request.get_json(force=True, silent=True) or {}
    owner_id = data.get('owner_id')
    viewer_id = data.get('viewer_id')
    moment_id = data.get('moment_id')

    if not owner_id or not viewer_id or not moment_id:
        return jsonify({"status": "error", "message": "Missing IDs"}), 400

    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT OR IGNORE INTO secret_access (owner_id, viewer_id, moment_id)
            VALUES (?, ?, ?)
        ''', (owner_id, viewer_id, moment_id))
        conn.commit()
        return jsonify({"status": "success", "message": "Access granted!"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/delete_private_moment/<int:moment_id>', methods=['DELETE'])
def delete_private_moment(moment_id):
    conn = get_db_connection()
    row = conn.execute('SELECT image_base64 FROM private_moments WHERE id = ?', (moment_id,)).fetchone()
    
    if not row:
        conn.close()
        return jsonify({"status": "error", "message": "Moment not found"}), 404
        
    filename = row['image_base64']
    if filename:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                print(f"Error deleting file: {e}")
                
    conn.execute('DELETE FROM private_moments WHERE id = ?', (moment_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "message": "Secret moment deleted successfully!"}), 200


@app.route('/get_messages/<int:user1_id>/<int:user2_id>', methods=['GET'])
def get_messages(user1_id, user2_id):
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT from_user_id, to_user_id, content, timestamp 
        FROM messages 
        WHERE (from_user_id = ? AND to_user_id = ?) 
           OR (from_user_id = ? AND to_user_id = ?)
        ORDER BY id ASC
    ''', (user1_id, user2_id, user2_id, user1_id)).fetchall()
    conn.close()

    messages = []
    for r in rows:
        messages.append({
            "sender": r['from_user_id'],
            "text": r['content'],
            "timestamp": r['timestamp']
        })
    return jsonify({"status": "success", "messages": messages}), 200


@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.get_json(force=True, silent=True) or {}
    from_id = data.get('from_user_id')
    to_id = data.get('to_user_id')
    content = data.get('content', '')

    if not from_id or not to_id or not content:
        return jsonify({"status": "error", "message": "Missing fields"}), 400

    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO messages (from_user_id, to_user_id, content)
            VALUES (?, ?, ?)
        ''', (from_id, to_id, content))
        conn.commit()
        return jsonify({"status": "success", "message": "Message sent!"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/post_comment', methods=['POST'])
def post_comment():
    data = request.get_json(force=True, silent=True) or {}
    profile_id = data.get('profile_user_id')
    commenter_id = data.get('commenter_user_id')
    commenter_name = data.get('commenter_name', 'Coffee Passersby')
    commenter_image = data.get('commenter_image', '')
    text = data.get('comment', '').strip()

    if not profile_id or not commenter_id or not text:
        return jsonify({"status": "error", "message": "Missing fields"}), 400

    lower_text = text.lower()
    negative_words = ['ugly', 'hate', 'bad', 'horrible', 'stupid', 'loser', 'trash', 'scam']
    if any(word in lower_text for word in negative_words):
        return jsonify({
            "status": "error", 
            "message": "Public wall keeps good vibes only! Save the spicy banter for private chat rooms ☕"
        }), 400

    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO profile_comments (profile_user_id, commenter_user_id, commenter_name, commenter_image, comment)
            VALUES (?, ?, ?, ?, ?)
        ''', (profile_id, commenter_id, commenter_name, commenter_image, text))
        conn.commit()
        return jsonify({"status": "success", "message": "Comment posted!"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/get_comments/<int:profile_user_id>', methods=['GET'])
def get_comments(profile_user_id):
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT id, commenter_user_id, commenter_name, commenter_image, comment, timestamp
        FROM profile_comments
        WHERE profile_user_id = ?
        ORDER BY id DESC
    ''', (profile_user_id,)).fetchall()
    conn.close()

    comments = []
    for r in rows:
        comments.append({
            "id": r['id'],
            "commenter_id": r['commenter_user_id'],
            "name": r['commenter_name'],
            "image": r['commenter_image'],
            "comment": r['comment'],
            "timestamp": r['timestamp']
        })
    return jsonify({"status": "success", "comments": comments}), 200

@app.route('/feed', methods=['GET'])
def get_feed():
    current_user_id = request.args.get('user_id', default=1, type=int)
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    conn = get_db_connection()
    if lat is not None and lng is not None:
        conn.execute('UPDATE users SET last_lat = ?, last_lng = ? WHERE id = ?', (lat, lng, current_user_id))
        conn.commit()
    
    cursor = conn.cursor()
    potential_matches = cursor.execute('''
        SELECT id, nickname, age, gender, coffee_shop, bio, profile_image, caffeine_status, last_lat, last_lng
        FROM users 
        WHERE id != ? AND last_lat IS NOT NULL AND last_lng IS NOT NULL
    ''', (current_user_id,)).fetchall()
    conn.close()

    feed_list = []
    MAX_DISTANCE_KM = 5.0

    for u in potential_matches:
        distance = haversine_distance(lat, lng, u['last_lat'], u['last_lng'])
        if distance <= MAX_DISTANCE_KM:
            avatar = u['profile_image']
            img_url = f"{request.host_url}uploads/{avatar}" if avatar else "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"
            
            feed_list.append({
                "id": u["id"],
                "name": u["nickname"] or "Anonymous",
                "age": str(u["age"] or 25),
                "shop": u["coffee_shop"] or "Local Cafe",
                "bio": u["bio"] or "Looking for good coffee and great conversation!",
                "image": img_url,
                "tags": ["Coffee Lover", u["caffeine_status"] or "Local", u["coffee_shop"] or "Explorer"],
                "distance_km": round(distance, 1)
            })
            
    feed_list.sort(key=lambda x: x['distance_km'])
    return jsonify({"status": "success", "feed": feed_list}), 200

@app.route('/uploads/<filename>')
def serve_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/user_profile/<int:user_id>', methods=['GET'])
def get_user_profile(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()

    if not user:
        return jsonify({
            "status": "success",
            "user": {
                "id": user_id,
                "nickname": "Coffee Lover",
                "age": 25,
                "coffee_shop": "Local Cafe",
                "bio": "Ready for coffee!",
                "image": "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=800&q=80"
            }
        }), 200

    avatar = user['profile_image']
    img_url = f"{request.host_url}uploads/{avatar}" if avatar else "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=800&q=80"

    return jsonify({
        "status": "success",
        "user": {
            "id": user["id"],
            "nickname": user["nickname"],
            "age": user["age"],
            "coffee_shop": user["coffee_shop"],
            "bio": user["bio"],
            "image": img_url,
            "caffeine_status": user["caffeine_status"] if "caffeine_status" in user.keys() else "Chilling"
        }
    }), 200


@app.route('/update_avatar', methods=['POST'])
def update_avatar():
    data = request.json or {}
    user_id = data.get('user_id', 1)
    image_b64 = data.get('image_base64')
    
    if not image_b64:
        return jsonify({"status": "error", "message": "No image uploaded"}), 400

    filename = secure_filename(f"avatar_{user_id}_{int(time.time())}.jpg")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    try:
        with open(filepath, "wb") as fh:
            fh.write(base64.b64decode(image_b64))
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error saving photo: {e}"}), 500

    conn = get_db_connection()
    conn.execute('UPDATE users SET profile_image = ? WHERE id = ?', (filename, user_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "avatar_url": f"{request.host_url}uploads/{filename}"}), 200

@app.route('/user_stats/<int:user_id>', methods=['GET'])
def get_user_stats(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    user = cursor.execute('SELECT coffee_shop FROM users WHERE id = ?', (user_id,)).fetchone()
    current_shop = user['coffee_shop'] if user else ""

    vibes_count = cursor.execute('SELECT COUNT(*) as count FROM users WHERE LOWER(coffee_shop) = LOWER(?) AND id != ?', (current_shop, user_id)).fetchone()['count']
    likes_count = cursor.execute('SELECT COUNT(*) as count FROM user_likes WHERE to_user_id = ?', (user_id,)).fetchone()['count']
    match_count = cursor.execute('''
        SELECT COUNT(*) as count FROM user_likes a
        JOIN user_likes b ON a.from_user_id = b.to_user_id AND a.to_user_id = b.from_user_id
        WHERE a.from_user_id = ?
    ''', (user_id,)).fetchone()['count']
    conn.close()

    return jsonify({"status": "success", "match_brew": match_count, "similar_vibes": vibes_count, "local_likes": likes_count}), 200


@app.route('/insight_details/<category>/<int:user_id>', methods=['GET'])
def get_insight_details(category, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    current_user = cursor.execute('SELECT coffee_shop FROM users WHERE id = ?', (user_id,)).fetchone()
    current_shop = current_user['coffee_shop'] if current_user else ""
    users_list = []
    
    if category == 'similar_vibes':
        rows = cursor.execute('SELECT id, nickname, age, coffee_shop, bio, profile_image FROM users WHERE LOWER(coffee_shop) = LOWER(?) AND id != ?', (current_shop, user_id)).fetchall()
        title = f"Similar Coffee Vibes ({current_shop})"
    elif category == 'local_likes':
        rows = cursor.execute('SELECT u.id, u.nickname, u.age, u.coffee_shop, u.bio, u.profile_image FROM users u JOIN user_likes l ON u.id = l.from_user_id WHERE l.to_user_id = ?', (user_id,)).fetchall()
        title = "Local Coffee Likes"
    elif category == 'match_brew':
        rows = cursor.execute('SELECT u.id, u.nickname, u.age, u.coffee_shop, u.bio, u.profile_image FROM users u JOIN user_likes a ON u.id = a.to_user_id JOIN user_likes b ON u.id = b.from_user_id WHERE a.from_user_id = ? AND b.to_user_id = ?', (user_id, user_id)).fetchall()
        title = "Match Brew (Mutual Sparks)"
    else:
        conn.close()
        return jsonify({"status": "error", "message": "Unknown category"}), 400

    conn.close()
    for r in rows:
        avatar = r['profile_image']
        img_url = f"{request.host_url}uploads/{avatar}" if avatar else "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=400&q=80"
        users_list.append({
            "id": r["id"],
            "name": r["nickname"] or "Coffee Lover",
            "age": str(r["age"] or ""),
            "shop": r["coffee_shop"] or "Local Spot",
            "bio": r["bio"] or "Looking for great coffee & conversation!",
            "image": img_url
        })

    return jsonify({"status": "success", "title": title, "users": users_list}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
