import base64
import os
import random
import sqlite3
import time
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def get_db_connection():
    conn = sqlite3.connect('coffee_sparks.db')
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    conn = get_db_connection()
    # 1. Users Table with all features & new columns
    conn.execute('''
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
            audio_intro TEXT
        )
    ''')
    
    # Safely add columns if missing in existing DBs
    for col, col_type in [('caffeine_status', "TEXT DEFAULT 'Craving an iced latte ☕'"), ('audio_intro', 'TEXT')]:
        try:
            conn.execute(f'ALTER TABLE users ADD COLUMN {col} {col_type}')
        except sqlite3.OperationalError:
            pass

    # 2. User Photos Table
    conn.execute('''
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
        conn.execute('ALTER TABLE user_photos ADD COLUMN is_private INTEGER DEFAULT 1')
    except sqlite3.OperationalError:
        pass

    # 3. User Likes Table
    conn.execute('''
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
    conn.execute('''
        CREATE TABLE IF NOT EXISTS date_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            cafe_name TEXT NOT NULL,
            meet_time TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(from_user_id) REFERENCES users(id),
            FOREIGN KEY(to_user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()


@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "success", "message": "Coffee Sparks server is awake!"})


@app.route('/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True) or {}
    
    email = data.get('email', f"user_{int(time.time())}@coffee.com")
    password = data.get('password', 'temporarypassword')
    real_name = data.get('real_name', 'Coffee Lover')
    nickname = data.get('nickname', real_name)
    age = int(data.get('age', 18))
    gender = data.get('gender', 'Man')
    coffee_shop = data.get('coffee_shop', 'Local Cafe')
    bio = data.get('bio', '')
    
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
            INSERT INTO users (email, password, real_name, nickname, age, gender, coffee_shop, bio, profile_image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (email, password, real_name, nickname, age, gender, coffee_shop, bio, avatar_filename))
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


@app.route('/update_status', methods=['POST'])
def update_status():
    data = request.json or {}
    user_id = data.get('user_id', 1)
    status = data.get('caffeine_status', 'Chilling at a cafe')
    
    conn = get_db_connection()
    conn.execute('UPDATE users SET caffeine_status = ? WHERE id = ?', (status, user_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "caffeine_status": status}), 200


@app.route('/create_date_invite', methods=['POST'])
def create_date_invite():
    data = request.json or {}
    from_user = data.get('from_user_id')
    to_user = data.get('to_user_id')
    cafe_name = data.get('cafe_name', 'Local Cafe')
    meet_time = data.get('meet_time', 'Tomorrow at 3 PM')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO date_invites (from_user_id, to_user_id, cafe_name, meet_time)
        VALUES (?, ?, ?, ?)
    ''', (from_user, to_user, cafe_name, meet_time))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Date invite sent!"}), 201


@app.route('/daily_prompt', methods=['GET'])
def get_daily_prompt():
    prompts = [
        "Dark roast purist or sweet caramel macchiato fan?",
        "What is your ultimate go-to pastry pairing with an iced latte?",
        "Morning espresso shot for energy or slow evening pour-over?",
        "Have you ever accidentally stayed at a coffee shop for over 4 hours?"
    ]
    return jsonify({"status": "success", "prompt": random.choice(prompts)}), 200


@app.route('/feed', methods=['GET'])
def get_feed():
    current_user_id = request.args.get('user_id', default=1, type=int)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    current_user = cursor.execute('SELECT * FROM users WHERE id = ?', (current_user_id,)).fetchone()
    current_shop = current_user['coffee_shop'] if current_user else ""

    users = cursor.execute('''
        SELECT id, nickname, age, gender, coffee_shop, bio, profile_image, caffeine_status,
               CASE WHEN LOWER(coffee_shop) = LOWER(?) THEN 1 ELSE 0 END as is_same_spot
        FROM users 
        WHERE id != ?
        ORDER BY is_same_spot DESC, id DESC
    ''', (current_shop, current_user_id)).fetchall()
    conn.close()

    feed_list = []
    for u in users:
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
            "is_same_spot": bool(u["is_same_spot"])
        })

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
                "real_name": "Coffee Explorer",
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
            "real_name": user["real_name"],
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
    user_id = request.form.get('user_id', 1, type=int)
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    filename = secure_filename(f"avatar_{user_id}_{int(time.time())}_{file.filename}")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    conn = get_db_connection()
    conn.execute('UPDATE users SET profile_image = ? WHERE id = ?', (filename, user_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "avatar_url": f"{request.host_url}uploads/{filename}"}), 200


@app.route('/upload_photo', methods=['POST'])
def upload_photo():
    user_id = request.form.get('user_id', 1, type=int)
    caption = request.form.get('caption', '')
    is_private = request.form.get('is_private', '1', type=str)
    is_private_int = 1 if is_private in ['1', 'true', 'True'] else 0
    
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    filename = secure_filename(f"user_{user_id}_{int(time.time())}_{file.filename}")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    conn = get_db_connection()
    conn.execute('INSERT INTO user_photos (user_id, image_filename, caption, is_private) VALUES (?, ?, ?, ?)',
                 (user_id, filename, caption, is_private_int))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "image_url": f"{request.host_url}uploads/{filename}"}), 201


@app.route('/toggle_photo_privacy', methods=['POST'])
def toggle_photo_privacy():
    data = request.json or {}
    photo_id = data.get('photo_id')
    user_id = data.get('user_id', 1)

    if not photo_id:
        return jsonify({"status": "error", "message": "Missing photo ID"}), 400

    conn = get_db_connection()
    photo = conn.execute('SELECT is_private FROM user_photos WHERE id = ? AND user_id = ?', (photo_id, user_id)).fetchone()
    if not photo:
        conn.close()
        return jsonify({"status": "error", "message": "Photo not found"}), 404

    new_status = 0 if photo['is_private'] == 1 else 1
    conn.execute('UPDATE user_photos SET is_private = ? WHERE id = ?', (new_status, photo_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "is_private": bool(new_status)}), 200


@app.route('/user_photos/<int:user_id>', methods=['GET'])
def get_user_photos(user_id):
    conn = get_db_connection()
    photos = conn.execute('SELECT id, image_filename, caption, is_private, uploaded_at FROM user_photos WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
    conn.close()

    result = []
    for p in photos:
        result.append({
            "id": p["id"],
            "image_url": f"{request.host_url}uploads/{p['image_filename']}",
            "caption": p["caption"] or "",
            "is_private": bool(p["is_private"])
        })
    return jsonify({"status": "success", "photos": result}), 200


@app.route('/like_user', methods=['POST'])
def like_user():
    data = request.json or {}
    from_user = data.get('from_user_id')
    to_user = data.get('to_user_id')

    if not from_user or not to_user:
        return jsonify({"status": "error", "message": "Missing user IDs"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO user_likes (from_user_id, to_user_id) VALUES (?, ?)', (from_user, to_user))
        conn.commit()
        mutual = cursor.execute('SELECT id FROM user_likes WHERE from_user_id = ? AND to_user_id = ?', (to_user, from_user)).fetchone()
        return jsonify({"status": "success", "is_match": mutual is not None}), 200
    finally:
        conn.close()


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
    setup_database()
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
