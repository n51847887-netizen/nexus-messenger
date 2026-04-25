from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
import os
import re
import uuid
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nexus-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///nexus.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', logger=True, engineio_logger=True)

# ─── MODELS ───────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    avatar_color = db.Column(db.String(7), default='#7c3aed')
    avatar_emoji = db.Column(db.String(10), default='👤')
    bio = db.Column(db.String(200), default='')
    online = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy=True)

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100))
    is_group = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))

    members = db.relationship('ChatMember', backref='chat', lazy=True)
    messages = db.relationship('Message', backref='chat', lazy=True, order_by='Message.created_at')

class ChatMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='chat_memberships')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    msg_type = db.Column(db.String(20), default='text')  # text, image, file, voice
    reply_to = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=True)
    edited = db.Column(db.Boolean, default=False)
    deleted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    reactions = db.relationship('Reaction', backref='message', lazy=True)

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)

def serialize_user(user, minimal=False):
    if minimal:
        return {
            'id': user.id,
            'uid': user.uid,
            'username': user.username,
            'display_name': user.display_name,
            'avatar_color': user.avatar_color,
            'avatar_emoji': user.avatar_emoji,
            'online': user.online,
        }
    return {
        'id': user.id,
        'uid': user.uid,
        'email': user.email,
        'username': user.username,
        'display_name': user.display_name,
        'avatar_color': user.avatar_color,
        'avatar_emoji': user.avatar_emoji,
        'bio': user.bio,
        'online': user.online,
        'last_seen': user.last_seen.isoformat(),
        'created_at': user.created_at.isoformat(),
    }

def serialize_message(msg):
    reactions_dict = {}
    for r in msg.reactions:
        if r.emoji not in reactions_dict:
            reactions_dict[r.emoji] = []
        reactions_dict[r.emoji].append(r.user_id)
    
    return {
        'id': msg.id,
        'uid': msg.uid,
        'chat_id': msg.chat_id,
        'sender': serialize_user(msg.sender, minimal=True),
        'content': msg.content if not msg.deleted else '🗑 Message deleted',
        'msg_type': msg.msg_type,
        'reply_to': msg.reply_to,
        'edited': msg.edited,
        'deleted': msg.deleted,
        'reactions': reactions_dict,
        'created_at': msg.created_at.isoformat(),
    }

def get_or_create_dm(user1_id, user2_id):
    # Find existing DM chat between these two users
    chats1 = set(m.chat_id for m in ChatMember.query.filter_by(user_id=user1_id).all())
    chats2 = set(m.chat_id for m in ChatMember.query.filter_by(user_id=user2_id).all())
    common = chats1 & chats2
    
    for chat_id in common:
        chat = Chat.query.get(chat_id)
        if not chat.is_group and len(chat.members) == 2:
            return chat
    
    # Create new DM
    chat = Chat(is_group=False, created_by=user1_id)
    db.session.add(chat)
    db.session.flush()
    
    m1 = ChatMember(chat_id=chat.id, user_id=user1_id)
    m2 = ChatMember(chat_id=chat.id, user_id=user2_id)
    db.session.add_all([m1, m2])
    db.session.commit()
    return chat

def serialize_chat(chat, current_user_id):
    members = [m.user for m in chat.members]
    last_msg = Message.query.filter_by(chat_id=chat.id).order_by(Message.created_at.desc()).first()
    
    if not chat.is_group:
        other = next((m for m in members if m.id != current_user_id), None)
        name = other.display_name if other else 'Unknown'
        avatar_color = other.avatar_color if other else '#7c3aed'
        avatar_emoji = other.avatar_emoji if other else '👤'
        online = other.online if other else False
    else:
        name = chat.name or ', '.join(m.display_name for m in members[:3])
        avatar_color = '#1e40af'
        avatar_emoji = '👥'
        online = False
    
    unread = 0  # Could implement read receipts later
    
    return {
        'id': chat.id,
        'uid': chat.uid,
        'name': name,
        'is_group': chat.is_group,
        'avatar_color': avatar_color,
        'avatar_emoji': avatar_emoji,
        'online': online,
        'members': [serialize_user(m, minimal=True) for m in members],
        'last_message': serialize_message(last_msg) if last_msg else None,
        'unread': unread,
    }

# ─── AUTH ROUTES ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    base = os.path.dirname(os.path.abspath(__file__))
    for p in [os.path.join(base, 'index.html'), os.path.join(base, 'templates', 'index.html')]:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    return 'index.html not found', 404

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email', '').lower().strip()
    username = data.get('username', '').lower().strip()
    display_name = data.get('display_name', '').strip()
    password = data.get('password', '')

    if not all([email, username, display_name, password]):
        return jsonify({'error': 'All fields required'}), 400
    
    if not re.match(r'^[\w.-]+@[\w.-]+\.\w+$', email):
        return jsonify({'error': 'Invalid email'}), 400
    
    if len(password) < 6:
        return jsonify({'error': 'Password too short (min 6 chars)'}), 400
    
    if not re.match(r'^[a-z0-9_]{3,30}$', username):
        return jsonify({'error': 'Username: 3-30 chars, letters/numbers/underscore'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409
    
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username taken'}), 409

    colors = ['#7c3aed', '#db2777', '#059669', '#d97706', '#2563eb', '#dc2626', '#0891b2']
    emojis = ['😎', '🚀', '🌟', '🔥', '⚡', '🎯', '💎', '🌈', '🦊', '🐉']
    
    user = User(
        email=email,
        username=username,
        display_name=display_name,
        password_hash=bcrypt.generate_password_hash(password).decode('utf-8'),
        avatar_color=random.choice(colors),
        avatar_emoji=random.choice(emojis),
    )
    db.session.add(user)
    db.session.commit()

    session.permanent = True
    session['user_id'] = user.id
    return jsonify({'user': serialize_user(user)}), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email', '').lower().strip()
    password = data.get('password', '')

    user = User.query.filter_by(email=email).first()
    if not user or not bcrypt.check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid email or password'}), 401

    user.online = True
    db.session.commit()

    session.permanent = True
    session['user_id'] = user.id
    return jsonify({'user': serialize_user(user)})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    user = get_current_user()
    if user:
        user.online = False
        user.last_seen = datetime.utcnow()
        db.session.commit()
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/me')
def me():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    return jsonify({'user': serialize_user(user)})

# ─── USER ROUTES ──────────────────────────────────────────────────────────────

@app.route('/api/users/search')
def search_users():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'users': []})
    
    users = User.query.filter(
        (User.username.ilike(f'%{q}%') | User.display_name.ilike(f'%{q}%')),
        User.id != user.id
    ).limit(20).all()
    
    return jsonify({'users': [serialize_user(u, minimal=True) for u in users]})

@app.route('/api/users/<username>')
def get_user(username):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    target = User.query.filter_by(username=username).first_or_404()
    return jsonify({'user': serialize_user(target)})

@app.route('/api/users/profile', methods=['PUT'])
def update_profile():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.json
    if 'display_name' in data and data['display_name'].strip():
        user.display_name = data['display_name'].strip()[:100]
    if 'bio' in data:
        user.bio = data['bio'][:200]
    if 'avatar_emoji' in data:
        user.avatar_emoji = data['avatar_emoji'][:10]
    if 'avatar_color' in data:
        user.avatar_color = data['avatar_color'][:7]
    
    db.session.commit()
    return jsonify({'user': serialize_user(user)})

# ─── CHAT ROUTES ──────────────────────────────────────────────────────────────

@app.route('/api/chats')
def get_chats():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    
    memberships = ChatMember.query.filter_by(user_id=user.id).all()
    chats = []
    for m in memberships:
        chats.append(serialize_chat(m.chat, user.id))
    
    # Sort by last message
    chats.sort(key=lambda c: c['last_message']['created_at'] if c['last_message'] else '0', reverse=True)
    return jsonify({'chats': chats})

@app.route('/api/chats/dm/<int:user_id>', methods=['POST'])
def create_dm(user_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    
    target = User.query.get_or_404(user_id)
    chat = get_or_create_dm(user.id, target.id)
    return jsonify({'chat': serialize_chat(chat, user.id)})

@app.route('/api/chats/group', methods=['POST'])
def create_group():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.json
    name = data.get('name', '').strip()
    member_ids = data.get('member_ids', [])
    
    if not name:
        return jsonify({'error': 'Group name required'}), 400
    
    chat = Chat(is_group=True, name=name, created_by=user.id)
    db.session.add(chat)
    db.session.flush()
    
    all_members = set([user.id] + member_ids)
    for uid in all_members:
        m = ChatMember(chat_id=chat.id, user_id=uid)
        db.session.add(m)
    
    db.session.commit()
    return jsonify({'chat': serialize_chat(chat, user.id)}), 201

@app.route('/api/chats/<int:chat_id>/messages')
def get_messages(chat_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401
    
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=user.id).first()
    if not member:
        return jsonify({'error': 'Access denied'}), 403
    
    before = request.args.get('before')
    limit = min(int(request.args.get('limit', 50)), 100)
    
    q = Message.query.filter_by(chat_id=chat_id)
    if before:
        q = q.filter(Message.id < int(before))
    
    messages = q.order_by(Message.created_at.desc()).limit(limit).all()
    messages.reverse()
    
    return jsonify({'messages': [serialize_message(m) for m in messages]})

# ─── SOCKETIO EVENTS ──────────────────────────────────────────────────────────

online_users = {}  # socket_id -> user_id

@socketio.on('connect')
def on_connect():
    user = get_current_user()
    if not user:
        return False
    
    online_users[request.sid] = user.id
    user.online = True
    db.session.commit()
    
    # Join all chat rooms
    for m in user.chat_memberships:
        join_room(f'chat_{m.chat_id}')
    
    # Notify contacts
    emit('user_online', {'user_id': user.id}, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    user_id = online_users.pop(request.sid, None)
    if user_id:
        user = User.query.get(user_id)
        if user:
            user.online = False
            user.last_seen = datetime.utcnow()
            db.session.commit()
            emit('user_offline', {'user_id': user_id, 'last_seen': user.last_seen.isoformat()}, broadcast=True)

@socketio.on('send_message')
def on_send_message(data):
    user = get_current_user()
    if not user:
        return
    
    chat_id = data.get('chat_id')
    content = data.get('content', '').strip()
    msg_type = data.get('msg_type', 'text')
    reply_to = data.get('reply_to')
    
    if not content or not chat_id:
        return
    
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=user.id).first()
    if not member:
        return
    
    msg = Message(
        chat_id=chat_id,
        sender_id=user.id,
        content=content[:4000],
        msg_type=msg_type,
        reply_to=reply_to,
    )
    db.session.add(msg)
    db.session.commit()
    
    emit('new_message', serialize_message(msg), room=f'chat_{chat_id}')

@socketio.on('edit_message')
def on_edit_message(data):
    user = get_current_user()
    if not user:
        return
    
    msg = Message.query.get(data.get('message_id'))
    if not msg or msg.sender_id != user.id or msg.deleted:
        return
    
    msg.content = data.get('content', '').strip()[:4000]
    msg.edited = True
    db.session.commit()
    
    emit('message_edited', serialize_message(msg), room=f'chat_{msg.chat_id}')

@socketio.on('delete_message')
def on_delete_message(data):
    user = get_current_user()
    if not user:
        return
    
    msg = Message.query.get(data.get('message_id'))
    if not msg or msg.sender_id != user.id:
        return
    
    msg.deleted = True
    db.session.commit()
    
    emit('message_deleted', {'message_id': msg.id, 'chat_id': msg.chat_id}, room=f'chat_{msg.chat_id}')

@socketio.on('react_message')
def on_react_message(data):
    user = get_current_user()
    if not user:
        return
    
    msg_id = data.get('message_id')
    emoji = data.get('emoji', '')[:10]
    
    msg = Message.query.get(msg_id)
    if not msg:
        return
    
    existing = Reaction.query.filter_by(message_id=msg_id, user_id=user.id, emoji=emoji).first()
    if existing:
        db.session.delete(existing)
    else:
        r = Reaction(message_id=msg_id, user_id=user.id, emoji=emoji)
        db.session.add(r)
    
    db.session.commit()
    emit('reaction_updated', serialize_message(msg), room=f'chat_{msg.chat_id}')

@socketio.on('typing')
def on_typing(data):
    user = get_current_user()
    if not user:
        return
    emit('user_typing', {
        'user_id': user.id,
        'username': user.display_name,
        'chat_id': data.get('chat_id'),
        'typing': data.get('typing', False)
    }, room=f'chat_{data.get("chat_id")}', include_self=False)

@socketio.on('join_chat')
def on_join_chat(data):
    user = get_current_user()
    if not user:
        return
    chat_id = data.get('chat_id')
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=user.id).first()
    if member:
        join_room(f'chat_{chat_id}')

# ─── MAIN ─────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)

