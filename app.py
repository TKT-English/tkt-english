import os
import json
import sqlite3
import random
import string
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = 'super_secret_key_change_me_in_production'

QUESTIONS_FILE = 'questions.json'
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'Zaq1xsw2'
SESSION_DURATION_HOURS = 3  # Длительность сессии ученика в часах


# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pin_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            student_name TEXT,
            is_used BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def generate_pin(length=6):
    return ''.join(random.choices(string.digits, k=length))


def load_questions():
    if os.path.exists(QUESTIONS_FILE):
        try:
            with open(QUESTIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка чтения {QUESTIONS_FILE}: {e}")
            return []
    return []


# --- ПРОВЕРКА ИСТЕЧЕНИЯ ВРЕМЕНИ ДЛЯ УЧЕНИКОВ ---
@app.before_request
def check_session_timeout():
    # Если зашел обычный ученик и у него задано время окончания сессии
    if session.get('user') and not session.get('is_admin'):
        expires_at = session.get('expires_at')
        if expires_at and time.time() > expires_at:
            session.clear()
            flash('Время действия вашего PIN-кода (3 часа) истекло. Доступ закрыт.')
            return redirect(url_for('login'))


# --- ОСНОВНЫЕ МАРШРУТЫ ---

@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))

    questions = load_questions()
    modules = sorted(list(set(q.get('module', 1) for q in questions if 'module' in q)))
    if not modules:
        modules = [1]

    is_admin = session.get('is_admin', False)
    username = session.get('name', 'Пользователь')

    return render_template('index.html', modules=modules, is_admin=is_admin, username=username)


# 1. Вход для учеников по PIN-коду
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        pin_code = request.form.get('pin_code', '').strip()

        if not pin_code:
            error = "Введите PIN-код!"
        else:
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()
            cursor.execute("SELECT id, student_name, is_used FROM pin_codes WHERE code = ?", (pin_code,))
            pin_entry = cursor.fetchone()

            if pin_entry:
                pin_id, student_name, is_used = pin_entry
                if is_used:
                    error = "Этот PIN-код уже был использован и больше недействителен!"
                else:
                    # Помечаем PIN как использованный в базе данных
                    cursor.execute("UPDATE pin_codes SET is_used = 1 WHERE id = ?", (pin_id,))
                    conn.commit()
                    conn.close()

                    # Фиксируем время окончания сессии (текущий timestamp + 3 часа)
                    expire_time = time.time() + (SESSION_DURATION_HOURS * 3600)

                    session.clear()
                    session['user'] = f"student_{pin_id}"
                    session['name'] = student_name if student_name else f"Ученик #{pin_code}"
                    session['is_admin'] = False
                    session['expires_at'] = expire_time
                    return redirect(url_for('index'))
            else:
                error = "Неверный PIN-код!"
            
            conn.close()

    return render_template('login.html', error=error)


# 2. Вход для администратора
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'GET':
        session.clear()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session.clear()
            session['user'] = ADMIN_USERNAME
            session['name'] = 'Администратор'
            session['is_admin'] = True
            return redirect(url_for('admin_page'))
        else:
            error = "Неверный логин или пароль администратора!"

    return render_template('admin_login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- АДМИН-ПАНЕЛЬ ---

@app.route('/admin')
def admin_page():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    questions = load_questions()
    return render_template('admin.html', questions=questions)


@app.route('/admin/upload_docx', methods=['POST'])
def upload_docx():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    file = request.files.get('file')
    if not file or not file.filename.endswith('.docx'):
        flash('Пожалуйста, выберите файл в формате .docx')
        return redirect(url_for('admin_page'))

    flash('Файл успешно загружен!')
    return redirect(url_for('admin_page'))


@app.route('/admin/pins', methods=['GET', 'POST'])
def admin_pins():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        student_name = request.form.get('student_name', '').strip()
        new_pin = generate_pin(6)

        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO pin_codes (code, student_name) VALUES (?, ?)", (new_pin, student_name))
            conn.commit()
            flash(f'Создан новый PIN: {new_pin}')
        except sqlite3.IntegrityError:
            flash('Ошибка генерации PIN, попробуйте еще раз.')
        finally:
            conn.close()

        return redirect(url_for('admin_pins'))

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, code, student_name, is_used, created_at FROM pin_codes ORDER BY id DESC")
    pins = cursor.fetchall()
    conn.close()

    return render_template('admin_pins.html', pins=pins)


# --- ПРОХОЖДЕНИЕ ТЕСТА И API ---

@app.route('/quiz')
def quiz():
    if 'user' not in session:
        return redirect(url_for('login'))

    questions = load_questions()
    module_filter = request.args.get('module')

    if module_filter and module_filter.isdigit():
        mod_num = int(module_filter)
        questions = [q for q in questions if q.get('module') == mod_num]

    return render_template('quiz.html', questions=questions)


@app.route('/api/time_left')
def get_time_left():
    if not session.get('user') or session.get('is_admin'):
        return jsonify({'time_left': 999999})
    
    expires_at = session.get('expires_at', 0)
    remaining = int(expires_at - time.time())
    
    return jsonify({
        'time_left': max(0, remaining)
    })


@app.route('/api/check_answers', methods=['POST'])
def check_answers():
    if 'user' not in session:
        return jsonify({"error": "Авторизуйтесь"}), 401

    user_answers = request.get_json() or {}
    questions = load_questions()

    score = 0
    results = {}

    for q in questions:
        q_id = str(q['id'])
        user_ans = user_answers.get(q_id)

        if q_id not in user_answers:
            continue

        if q.get('type') == 'matching':
            correct_pairs = q.get('pairs', [])
            is_correct = True

            for pair in correct_pairs:
                key = pair.get('left')
                expected_val = pair.get('right')

                actual_val = None
                if isinstance(user_ans, dict):
                    for u_k, u_v in user_ans.items():
                        norm_u_k = None if u_k in ['', 'null', 'None', '__NO_PAIR__'] else u_k
                        norm_key = None if key in ['', 'null', 'None', '__NO_PAIR__'] else key
                        if norm_u_k == norm_key:
                            actual_val = u_v
                            break

                if actual_val in ['', 'null', 'None', '__NO_PAIR__']:
                    actual_val = None
                if expected_val in ['', 'null', 'None']:
                    expected_val = None

                if actual_val != expected_val:
                    is_correct = False
                    break

            results[q_id] = is_correct
            if is_correct:
                score += 1
        else:
            correct_ans = str(q.get('correct', '')).strip()
            user_str = str(user_ans).strip() if user_ans is not None else ""
            is_correct = (user_str == correct_ans)
            results[q_id] = is_correct
            if is_correct:
                score += 1

    return jsonify({
        'score': score,
        'total': len(user_answers),
        'results': results
    })


if __name__ == '__main__':
    print("Сервер запущен!")
    print("Вход для учеников: http://127.0.0.1:5000/login")
    print("Вход для админа: http://127.0.0.1:5000/admin/login")
    app.run(host='0.0.0.0', port=5000, debug=True)