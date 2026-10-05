import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

community_bp = Blueprint('community', __name__)
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'notes.db'


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_community_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS community_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'General',
            author_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS community_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            author_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (post_id) REFERENCES community_posts(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS community_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            UNIQUE(post_id, user_name),
            FOREIGN KEY (post_id) REFERENCES community_posts(id) ON DELETE CASCADE
        );
    ''')
    conn.commit()
    conn.close()


def current_user_name():
    # Change/add a session key here if your existing Google login uses another one.
    return (
        session.get('user_name') or
        session.get('name') or
        session.get('google_name') or
        session.get('email') or
        'Student'
    )


@community_bp.route('/community')
def community():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip() or 'All'
    conn = get_db()

    sql = '''
        SELECT p.*,
               (SELECT COUNT(*) FROM community_comments c WHERE c.post_id = p.id) AS comment_count,
               (SELECT COUNT(*) FROM community_likes l WHERE l.post_id = p.id) AS like_count
        FROM community_posts p
        WHERE 1=1
    '''
    params = []
    if q:
        sql += ' AND (p.title LIKE ? OR p.content LIKE ?)'
        params.extend([f'%{q}%', f'%{q}%'])
    if category != 'All':
        sql += ' AND p.category = ?'
        params.append(category)
    sql += ' ORDER BY p.id DESC'

    posts = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template('community.html', posts=posts, q=q, category=category)


@community_bp.route('/community/create', methods=['GET', 'POST'])
def create_post():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        category = request.form.get('category', 'General').strip()

        if not title or not content:
            flash('Please enter both a title and your post.', 'error')
            return render_template('community_create.html')
        if len(title) > 150 or len(content) > 5000:
            flash('Your title or post is too long.', 'error')
            return render_template('community_create.html')

        conn = get_db()
        conn.execute('''
            INSERT INTO community_posts (title, content, category, author_name, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (title, content, category, current_user_name(),
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        return redirect(url_for('community.community'))

    return render_template('community_create.html')


@community_bp.route('/community/post/<int:post_id>')
def view_post(post_id):
    conn = get_db()
    post = conn.execute('''
        SELECT p.*,
               (SELECT COUNT(*) FROM community_likes l WHERE l.post_id = p.id) AS like_count
        FROM community_posts p WHERE p.id = ?
    ''', (post_id,)).fetchone()

    if post is None:
        conn.close()
        return 'Post not found', 404

    comments = conn.execute(
        'SELECT * FROM community_comments WHERE post_id = ? ORDER BY id ASC',
        (post_id,)
    ).fetchall()

    user = current_user_name()
    liked = conn.execute(
        'SELECT 1 FROM community_likes WHERE post_id = ? AND user_name = ?',
        (post_id, user)
    ).fetchone() is not None

    conn.close()
    return render_template('community_post.html', post=post, comments=comments, liked=liked)


@community_bp.route('/community/post/<int:post_id>/comment', methods=['POST'])
def add_comment(post_id):
    content = request.form.get('content', '').strip()
    if not content:
        flash('Comment cannot be empty.', 'error')
        return redirect(url_for('community.view_post', post_id=post_id))
    if len(content) > 2000:
        flash('Comment is too long.', 'error')
        return redirect(url_for('community.view_post', post_id=post_id))

    conn = get_db()
    if not conn.execute('SELECT 1 FROM community_posts WHERE id = ?', (post_id,)).fetchone():
        conn.close()
        return 'Post not found', 404

    conn.execute('''
        INSERT INTO community_comments (post_id, content, author_name, created_at)
        VALUES (?, ?, ?, ?)
    ''', (post_id, content, current_user_name(),
          datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()
    return redirect(url_for('community.view_post', post_id=post_id))


@community_bp.route('/community/post/<int:post_id>/like', methods=['POST'])
def toggle_like(post_id):
    user = current_user_name()
    conn = get_db()
    if not conn.execute('SELECT 1 FROM community_posts WHERE id = ?', (post_id,)).fetchone():
        conn.close()
        return 'Post not found', 404

    existing = conn.execute(
        'SELECT id FROM community_likes WHERE post_id = ? AND user_name = ?',
        (post_id, user)
    ).fetchone()
    if existing:
        conn.execute('DELETE FROM community_likes WHERE id = ?', (existing['id'],))
    else:
        conn.execute(
            'INSERT OR IGNORE INTO community_likes (post_id, user_name) VALUES (?, ?)',
            (post_id, user)
        )
    conn.commit()
    conn.close()
    return redirect(url_for('community.view_post', post_id=post_id))
