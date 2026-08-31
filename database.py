import sqlite3

def setup_database():
    # This creates the database file (or connects to it if it already exists)
    conn = sqlite3.connect('coffee_sparks.db')
    cursor = conn.cursor()

    print("Building the database foundation...")

    # 1. USERS TABLE
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            real_name TEXT,
            nickname TEXT,
            age INTEGER,
            gender TEXT,
            coffee_shop TEXT,
            bio TEXT,
            profile_pic_url TEXT
        )
    ''')
    print("- Users table created.")

    # 2. MATCHES TABLE (The "Sparks")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id_1 INTEGER,
            user_id_2 INTEGER,
            status TEXT, -- 'pending' or 'sparked'
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id_1) REFERENCES users(id),
            FOREIGN KEY(user_id_2) REFERENCES users(id)
        )
    ''')
    print("- Matches table created.")

    # 3. MESSAGES TABLE (The Inbox)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            sender_id INTEGER,
            message_text TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(match_id) REFERENCES matches(id),
            FOREIGN KEY(sender_id) REFERENCES users(id)
        )
    ''')
    print("- Messages table created.")

    # 4. PRIVATE GALLERY TABLE (The Locked Photos)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS private_gallery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            image_url TEXT NOT NULL,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    print("- Private Gallery table created.")

    # Save and close
    conn.commit()
    conn.close()
    print("Database setup complete! coffee_sparks.db is ready.")

if __name__ == '__main__':
    setup_database()
