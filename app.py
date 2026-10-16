import os
import datetime
from flask import Flask, render_style, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# PDF reportlab
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
import io

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_school_key_12345')

# Настройка подключения к базе данных (PostgreSQL на Render / SQLite локально)
db_url = os.environ.get('DATABASE_URL', 'sqlite:///school_class.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db = SQLAlchemy(app)

# ----------------- МОДЕЛИ БАЗЫ ДАННЫХ -----------------

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False) # 'admin' или 'student'
    full_name = db.Column(db.String(150), nullable=False)
    plain_password = db.Column(db.String(100), nullable=True)

class JournalGrade(db.Model):
    __tablename__ = 'journal_grades'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    grade = db.Column(db.String(10), nullable=False)

class TermGrade(db.Model):
    __tablename__ = 'term_grades'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    term = db.Column(db.String(20), nullable=False)
    grade = db.Column(db.String(10), nullable=False)

class Homework(db.Model):
    __tablename__ = 'homework'
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    file_path = db.Column(db.String(255), nullable=True)
    date = db.Column(db.String(20), nullable=False)

class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date = db.Column(db.String(20), nullable=False)

class CalendarEvent(db.Model):
    __tablename__ = 'calendar_events'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    date = db.Column(db.String(20), nullable=False)

class PortalImage(db.Model):
    __tablename__ = 'portal_images'
    id = db.Column(db.Integer, primary_key=True)
    image_type = db.Column(db.String(50), unique=True, nullable=False) # 'schedule' или 'exams'
    file_path = db.Column(db.String(255), nullable=False)

class Note(db.Model):
    __tablename__ = 'notes'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False) # ID или 'all'
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date = db.Column(db.String(20), nullable=False)

# Списки fənn и yarımil
SUBJECTS = [
    'Azərbaycan dili', 'Ədəbiyyat', 'Xarici dil (İngilis)', 'Riyaziyyat',
    'İnformatika', 'Azərbaycan tarixi', 'Ümumi tarix', 'Fizika',
    'Kimya', 'Biologiya', 'Coğrafiya', 'Fiziki tərbiyə', 'Gənclərin çağırışaqədərki hazırlığı'
]

TERMS = ['I Yarımil', 'II Yarımil', 'İllik']

# ----------------- ИНИЦИАЛИЗАЦИЯ И СОЗДАНИЕ ТАБЛИЦ -----------------

def init_db():
    with app.app_context():
        db.create_all()
        # Проверяем наличие учетной записи администратора
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin_user = User(
                username='admin',
                password_hash=generate_password_hash('admin123'),
                role='admin',
                full_name='Məktəb Rəhbərliyi / Müəllim',
                plain_password='admin123'
            )
            db.session.add(admin_user)
            db.session.commit()

init_db()

# ----------------- МАРШРУТЫ (ROUTES) -----------------

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('admin' if session['role'] == 'admin' else 'student'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    user = User.query.filter_by(username=username).first()

    if user and check_password_hash(user.password_hash, password):
        session['user_id'] = user.id
        session['role'] = user.role
        session['full_name'] = user.full_name
        return redirect(url_for('admin' if user.role == 'admin' else 'student'))
    else:
        flash('İstifadəçi adı və ya şifrə yanlışdır!', 'danger')
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- ПАНЕЛЬ УЧИТЕЛЯ ---
@app.route('/admin')
def admin():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))

    students = User.query.filter_by(role='student').order_by(User.full_name).all()
    selected_student_id = request.args.get('student_id', type=int)
    if not selected_student_id and students:
        selected_student_id = students[0].id

    # Генерация дат текущей недели
    today = datetime.date.today()
    start_of_week = today - datetime.timedelta(days=today.weekday())
    journal_dates = [(start_of_week + datetime.timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6)]

    # Загрузка оценок
    journal_matrix = {}
    if selected_student_id:
        j_grades = JournalGrade.query.filter_by(student_id=selected_student_id).all()
        for g in j_grades:
            journal_matrix[(g.subject, g.date)] = g.grade

    term_matrix = {}
    t_grades = TermGrade.query.all()
    for g in t_grades:
        term_matrix[(g.student_id, g.subject, g.term)] = g.grade

    homeworks = Homework.query.order_by(Homework.id.desc()).all()
    announcements = Announcement.query.order_by(Announcement.id.desc()).all()
    notes = Note.query.order_by(Note.id.desc()).all()
    
    # Картинки расписания
    images = {}
    p_imgs = PortalImage.query.all()
    for img in p_imgs:
        images[img.image_type] = img.file_path

    # Добавляем имена студентов к заметкам
    notes_with_names = []
    for n in notes:
        st_name = "Bütün valideynlər"
        if n.student_id != 'all':
            st = User.query.get(int(n.student_id))
            if st:
                st_name = st.full_name
        notes_with_names.append({
            'id': n.id, 'title': n.title, 'content': n.content,
            'date': n.date, 'student_id': n.student_id, 'student_name': st_name
        })

    return render_template('admin.html',
                           students=students,
                           selected_student_id=selected_student_id,
                           subjects=SUBJECTS,
                           terms=TERMS,
                           journal_dates=journal_dates,
                           journal_matrix=journal_matrix,
                           term_matrix=term_matrix,
                           homeworks=homeworks,
                           announcements=announcements,
                           notes=notes_with_names,
                           images=images)

# --- API СОХРАНЕНИЯ ОЦЕНОК ---
@app.route('/api/journal/save_grade', methods=['POST'])
def save_journal_grade():
    if session.get('role') != 'admin':
        return jsonify({'success': False}), 403
    data = request.json
    student_id = int(data['student_id'])
    subject = data['subject']
    date = data['date']
    grade = data['grade']

    entry = JournalGrade.query.filter_by(student_id=student_id, subject=subject, date=date).first()
    if grade == "":
        if entry:
            db.session.delete(entry)
    else:
        if entry:
            entry.grade = grade
        else:
            entry = JournalGrade(student_id=student_id, subject=subject, date=date, grade=grade)
            db.session.add(entry)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/journal/save_term_grade', methods=['POST'])
def save_term_grade():
    if session.get('role') != 'admin':
        return jsonify({'success': False}), 403
    data = request.json
    student_id = int(data['student_id'])
    subject = data['subject']
    term = data['term']
    grade = data['grade']

    entry = TermGrade.query.filter_by(student_id=student_id, subject=subject, term=term).first()
    if grade == "":
        if entry:
            db.session.delete(entry)
    else:
        if entry:
            entry.grade = grade
        else:
            entry = TermGrade(student_id=student_id, subject=subject, term=term, grade=grade)
            db.session.add(entry)
    db.session.commit()
    return jsonify({'success': True})

# --- УПРАВЛЕНИЕ УЧЕНИКАМИ ---
@app.route('/admin/add_student', methods=['POST'])
def add_student():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    full_name = request.form.get('full_name')
    username = request.form.get('username')
    password = request.form.get('password')

    if User.query.filter_by(username=username).first():
        flash('Bu istifadəçi adı artıq mövcuddur!', 'danger')
    else:
        new_s = User(
            username=username,
            password_hash=generate_password_hash(password),
            role='student',
            full_name=full_name,
            plain_password=password
        )
        db.session.add(new_s)
        db.session.commit()
        flash('Şagird uğurla əlavə edildi!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete_student/<int:id>', methods=['POST'])
def delete_student(id):
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    s = User.query.get(id)
    if s:
        JournalGrade.query.filter_by(student_id=id).delete()
        TermGrade.query.filter_by(student_id=id).delete()
        db.session.delete(s)
        db.session.commit()
        flash('Şagird silindi!', 'warning')
    return redirect(url_for('admin'))

# --- EV TAPŞIRIĞI ---
@app.route('/admin/add_homework', methods=['POST'])
def add_homework():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    subject = request.form.get('subject')
    description = request.form.get('description')
    file = request.files.get('file')
    filename = None
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    hw = Homework(subject=subject, description=description, file_path=filename, date=datetime.date.today().strftime('%d.%m.%Y'))
    db.session.add(hw)
    db.session.commit()
    flash('Ev tapşırığı əlavə olundu!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/edit_homework/<int:id>', methods=['POST'])
def edit_homework(id):
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    hw = Homework.query.get(id)
    if hw:
        hw.subject = request.form.get('subject')
        hw.description = request.form.get('description')
        file = request.files.get('file')
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            hw.file_path = filename
        db.session.commit()
        flash('Düzəliş edildi!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete_homework/<int:id>', methods=['POST'])
def delete_homework(id):
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    hw = Homework.query.get(id)
    if hw:
        db.session.delete(hw)
        db.session.commit()
        flash('Tapşırıq silindi!', 'info')
    return redirect(url_for('admin'))

# --- ELANLAR ---
@app.route('/admin/add_announcement', methods=['POST'])
def add_announcement():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    ann = Announcement(
        title=request.form.get('title'),
        content=request.form.get('content'),
        date=datetime.date.today().strftime('%d.%m.%Y')
    )
    db.session.add(ann)
    db.session.commit()
    flash('Elan dərc olundu!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/edit_announcement/<int:id>', methods=['POST'])
def edit_announcement(id):
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    ann = Announcement.query.get(id)
    if ann:
        ann.title = request.form.get('title')
        ann.content = request.form.get('content')
        db.session.commit()
        flash('Elan yeniləndi!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete_announcement/<int:id>', methods=['POST'])
def delete_announcement(id):
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    ann = Announcement.query.get(id)
    if ann:
        db.session.delete(ann)
        db.session.commit()
        flash('Elan silindi!', 'info')
    return redirect(url_for('admin'))

# --- XƏBƏRDARLIQLAR ---
@app.route('/admin/add_note', methods=['POST'])
def add_note():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    note = Note(
        student_id=request.form.get('student_id'),
        title=request.form.get('title'),
        content=request.form.get('content'),
        date=datetime.date.today().strftime('%d.%m.%Y')
    )
    db.session.add(note)
    db.session.commit()
    flash('Xəbərdarlıq göndərildi!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/edit_note/<int:id>', methods=['POST'])
def edit_note(id):
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    note = Note.query.get(id)
    if note:
        note.student_id = request.form.get('student_id')
        note.title = request.form.get('title')
        note.content = request.form.get('content')
        db.session.commit()
        flash('Xəbərdarlıq yeniləndi!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete_note/<int:id>', methods=['POST'])
def delete_note(id):
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    note = Note.query.get(id)
    if note:
        db.session.delete(note)
        db.session.commit()
        flash('Xəbərdarlıq silindi!', 'info')
    return redirect(url_for('admin'))

# --- ŞƏKİLLƏR (CƏDVƏL/İMTAHAN) ---
@app.route('/admin/upload_portal_image', methods=['POST'])
def upload_portal_image():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    image_type = request.form.get('image_type')
    file = request.files.get('file')

    if file and file.filename != '':
        filename = secure_filename(f"{image_type}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        p_img = PortalImage.query.filter_by(image_type=image_type).first()
        if p_img:
            p_img.file_path = filename
        else:
            p_img = PortalImage(image_type=image_type, file_path=filename)
            db.session.add(p_img)
        db.session.commit()
        flash('Şəkil yeniləndi!', 'success')
    return redirect(url_for('admin'))

# --- ИНТЕРАКТИВНЫЙ КАЛЕНДАРЬ API ---
@app.route('/api/events', methods=['GET'])
def get_events():
    events = CalendarEvent.query.all()
    return jsonify([{'id': e.id, 'title': e.title, 'start': e.date} for e in events])

@app.route('/api/events/add', methods=['POST'])
def add_event():
    if session.get('role') != 'admin':
        return jsonify({'success': False}), 403
    data = request.json
    ev = CalendarEvent(title=data['title'], date=data['date'])
    db.session.add(ev)
    db.session.commit()
    return jsonify({'success': True, 'id': ev.id})

@app.route('/api/events/delete/<int:id>', methods=['DELETE'])
def delete_event(id):
    if session.get('role') != 'admin':
        return jsonify({'success': False}), 403
    ev = CalendarEvent.query.get(id)
    if ev:
        db.session.delete(ev)
        db.session.commit()
    return jsonify({'success': True})

# --- ПАНЕЛЬ УЧЕНИКА / ВАЛИДЕЙНА ---
@app.route('/student')
def student():
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('index'))

    student_id = session['user_id']
    st_user = User.query.get(student_id)

    today = datetime.date.today()
    start_of_week = today - datetime.timedelta(days=today.weekday())
    journal_dates = [(start_of_week + datetime.timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6)]

    j_grades = JournalGrade.query.filter_by(student_id=student_id).all()
    journal_matrix = {(g.subject, g.date): g.grade for g in j_grades}

    t_grades = TermGrade.query.filter_by(student_id=student_id).all()
    term_matrix = {(g.subject, g.term): g.grade for g in t_grades}

    homeworks = Homework.query.order_by(Homework.id.desc()).all()
    announcements = Announcement.query.order_by(Announcement.id.desc()).all()
    
    notes = Note.query.filter((Note.student_id == str(student_id)) | (Note.student_id == 'all')).order_by(Note.id.desc()).all()

    images = {}
    p_imgs = PortalImage.query.all()
    for img in p_imgs:
        images[img.image_type] = img.file_path

    return render_template('student.html',
                           student=st_user,
                           subjects=SUBJECTS,
                           terms=TERMS,
                           journal_dates=journal_dates,
                           journal_matrix=journal_matrix,
                           term_matrix=term_matrix,
                           homeworks=homeworks,
                           announcements=announcements,
                           notes=notes,
                           images=images)

# --- ГЕНЕРАЦИЯ ОФИЦИАЛЬНОГО PDF ТАБЕЛЯ ---
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#718096"))
        self.drawRightString(280 * 2.83465, 12 * 2.83465, f"Səhifə {self._pageNumber} / {page_count}")

@app.route('/admin/print_tabel/<int:student_id>')
def print_tabel(student_id):
    student = User.query.get_or_404(student_id)

    j_grades = JournalGrade.query.filter_by(student_id=student_id).all()
    dates_set = sorted(list(set(g.date for g in j_grades)))
    journal_matrix = {(g.subject, g.date): g.grade for g in j_grades}

    t_grades = TermGrade.query.filter_by(student_id=student_id).all()
    term_matrix = {(g.subject, g.term): g.grade for g in t_grades}

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15 * 2.83465,
        rightMargin=15 * 2.83465,
        topMargin=15 * 2.83465,
        bottomMargin=18 * 2.83465
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=16, leading=20, alignment=1, textColor=colors.HexColor("#1A365D"))
    subtitle_style = ParagraphStyle('SubTitleStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=11, leading=14, alignment=1, textColor=colors.HexColor("#4A5568"))
    th_style = ParagraphStyle('THStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, alignment=1, textColor=colors.white)
    td_left = ParagraphStyle('TDLeft', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, alignment=0, textColor=colors.HexColor("#2D3748"))
    td_center = ParagraphStyle('TDCenter', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10, alignment=1, textColor=colors.HexColor("#1A202C"))

    elements = []
    elements.append(Paragraph("MƏKTƏB TABELİ VƏ QİYMƏT ÇIXARIŞI", title_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(f"<b>Şagird:</b> {student.full_name} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Tarix:</b> {datetime.date.today().strftime('%d.%m.%Y')}", subtitle_style))
    elements.append(Spacer(1, 10))

    header = [Paragraph("Fənn", th_style)]
    for d in dates_set:
        header.append(Paragraph(f"{d[8:]}.{d[5:7]}", th_style))
    for t in TERMS:
        header.append(Paragraph(t, th_style))

    table_data = [header]

    for subj in SUBJECTS:
        row = [Paragraph(subj, td_left)]
        for d in dates_set:
            val = journal_matrix.get((subj, d), "")
            row.append(Paragraph(val, td_center))
        for t in TERMS:
            val = term_matrix.get((subj, t), "")
            row.append(Paragraph(f"<b>{val}</b>" if val else "", td_center))
        table_data.append(row)

    col_widths = [140]
    num_other_cols = len(dates_set) + len(TERMS)
    if num_other_cols > 0:
        other_width = (800 - 140) / num_other_cols
        col_widths.extend([other_width] * num_other_cols)

    tabel_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    t_style = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]

    for i in range(1, len(table_data)):
        bg = colors.HexColor("#F7FAFC") if i % 2 == 0 else colors.white
        t_style.append(('BACKGROUND', (0, i), (-1, i), bg))

    tabel_table.setStyle(TableStyle(t_style))
    elements.append(tabel_table)

    doc.build(elements, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"tabel_{student.username}.pdf", mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True)