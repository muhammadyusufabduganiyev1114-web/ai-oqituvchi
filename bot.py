
import os
import logging
import sqlite3
import html

from groq import AsyncGroq
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# 1. SOZLAMALAR
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()
GROQ_MODEL = os.getenv(
    "GROQ_MODEL", "openai/gpt-oss-20b"
).strip()
DATABASE_PATH = os.getenv(
    "DATABASE_PATH", "edu_ai.sqlite3"
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("edu_ai")

groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


def is_admin(user_id):
    return bool(ADMIN_ID) and str(user_id) == ADMIN_ID


# =========================
# 2. MA'LUMOTLAR BAZASI
# =========================

def db():
    return sqlite3.connect(DATABASE_PATH)


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                subject TEXT NOT NULL,
                experience TEXT NOT NULL,
                contact TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT,
                file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                score INTEGER NOT NULL,
                total INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def save_user(user):
    with db() as conn:
        conn.execute("""
            INSERT INTO users (user_id, full_name, username)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                full_name=excluded.full_name,
                username=excluded.username
        """, (
            user.id,
            user.full_name or "",
            user.username or "",
        ))


# =========================
# 3. MENYU
# =========================

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🤖 AI o‘qituvchi", "📝 Test ishlash"],
        ["👨‍🏫 Ustozlar", "📚 Video darsliklar"],
        ["➕ Ustoz bo‘lish", "ℹ️ Yordam"],
    ],
    resize_keyboard=True,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    context.user_data.pop("flow", None)

    await update.message.reply_text(
        f"Assalomu alaykum, {user.first_name}! 👋\n\n"
        "Men *Edu AI* — sizning sun’iy intellekt yordamchingizman.\n\n"
        "📖 Mavzularni tushuntiraman\n"
        "📝 Testlar orqali bilimlaringizni sinayman\n"
        "👨‍🏫 Ustoz topishga yordam beraman\n"
        "🎥 Video darsliklarni taqdim etaman\n\n"
        "Kerakli bo‘limni tanlang!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_MENU,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 *Edu AI buyruqlari*\n\n"
        "/start — asosiy menyu\n"
        "/quiz — test ishlash\n"
        "/teachers — ustozlar ro‘yxati\n"
        "/lessons — video darsliklar\n"
        "/become_teacher — ustoz sifatida ro‘yxatdan o‘tish\n"
        "/cancel — joriy jarayonni bekor qilish\n\n"
        "Administrator: /admin",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_MENU,
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("flow", None)
    context.user_data.pop("teacher_form", None)
    context.user_data.pop("quiz", None)
    await update.message.reply_text(
        "Jarayon bekor qilindi.",
        reply_markup=MAIN_MENU,
    )


# =========================
# 4. GROQ AI O‘QITUVCHI
# =========================

async def ask_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not groq_client:
        await update.message.reply_text(
            "AI hozir sozlanmagan. Administrator "
            "FadeHost sozlamalarida GROQ_API_KEY ni tekshirishi kerak."
        )
        return

    user_text = update.message.text.strip()

    if not user_text:
        return

    history = context.user_data.setdefault("ai_history", [])
    history.append({"role": "user", "content": user_text})
    history[:] = history[-10:]

    system_prompt = (
        "Sen Edu AI nomli bilimdon, xushmuomala va sabrli o‘qituvchisan. "
        "Asosan o‘zbek tilida javob ber. O‘quvchining savolini tushun, "
        "mavzuni sodda va bosqichma-bosqich tushuntir. "
        "Matematika masalalarida yechim yo‘lini ko‘rsat. "
        "Ingliz tili savollarida grammatikani izohla va kerak bo‘lsa "
        "o‘zbekcha tarjima ber. O‘quvchi faqat javob emas, "
        "mavzuni tushunib olishi uchun yordam ber. "
        "Bilmagan ma’lumotingni to‘qib chiqarma."
    )

    try:
        response = await groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                *history,
            ],
            temperature=0.4,
            max_completion_tokens=1500,
        )

        answer = response.choices[0].message.content or (
            "Kechirasiz, hozir javob tayyorlay olmadim."
        )

        history.append({"role": "assistant", "content": answer})
        history[:] = history[-10:]

        # Telegram xabari uzun bo‘lsa, qismlarga ajratiladi.
        for i in range(0, len(answer), 4000):
            await update.message.reply_text(answer[i:i + 4000])

    except Exception:
        logger.exception("Groq AI xatosi")
        await update.message.reply_text(
            "AI bilan bog‘lanishda xatolik yuz berdi. "
            "Birozdan so‘ng qayta urinib ko‘ring."
        )


# =========================
# 5. TEST TIZIMI
# =========================

QUIZZES = {
    "english": {
        "title": "Ingliz tili",
        "questions": [
            ("She ___ to school every day.", ["go", "goes", "going", "gone"], 1),
            ("I have lived here ___ 2020.", ["for", "at", "since", "from"], 2),
            ("If I ___ rich, I would travel.", ["am", "was", "were", "be"], 2),
            ("They ___ dinner when I arrived.", ["had", "were having", "have", "are having"], 1),
            ("Choose the synonym of 'rapid'.", ["slow", "quick", "weak", "late"], 1),
        ],
    },
    "math": {
        "title": "Matematika",
        "questions": [
            ("12 × 8 = ?", ["86", "92", "96", "108"], 2),
            ("x + 7 = 15. x = ?", ["6", "7", "8", "9"], 2),
            ("144 ning kvadrat ildizi?", ["10", "11", "12", "14"], 2),
            ("3² + 4² = ?", ["12", "25", "49", "7"], 1),
            ("200 ning 15 foizi?", ["15", "20", "30", "35"], 2),
        ],
    },
    "general": {
        "title": "Umumiy bilim",
        "questions": [
            ("O‘zbekiston poytaxti qaysi?", ["Samarqand", "Buxoro", "Toshkent", "Andijon"], 2),
            ("Bir yilda nechta oy bor?", ["10", "11", "12", "13"], 2),
            ("Yerning tabiiy yo‘ldoshi?", ["Quyosh", "Oy", "Mars", "Venera"], 1),
            ("Suvning kimyoviy formulasi?", ["CO2", "O2", "H2O", "NaCl"], 2),
            ("Kompyuterning asosiy hisoblash qurilmasi?", ["CPU", "Printer", "Monitor", "Sichqoncha"], 0),
        ],
    },
}


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🇬🇧 Ingliz tili", callback_data="quizcat_english")],
        [InlineKeyboardButton("➗ Matematika", callback_data="quizcat_math")],
        [InlineKeyboardButton("🌍 Umumiy bilim", callback_data="quizcat_general")],
    ]
    await update.message.reply_text(
        "Qaysi yo‘nalishda test ishlaysiz?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def send_quiz_question(chat_id, context):
    quiz = context.user_data.get("quiz")

    if not quiz:
        return

    questions = QUIZZES[quiz["category"]]["questions"]
    index = quiz["index"]

    if index >= len(questions):
        score = quiz["score"]
        total = len(questions)
        category = quiz["category"]

        with db() as conn:
            conn.execute(
                "INSERT INTO quiz_results (user_id, category, score, total) "
                "VALUES (?, ?, ?, ?)",
                (quiz["user_id"], category, score, total),
            )

        context.user_data.pop("quiz", None)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🏁 *Test yakunlandi!*\n\n"
                f"Yo‘nalish: {QUIZZES[category]['title']}\n"
                f"Natija: *{score}/{total}*\n\n"
                + (
                    "Ajoyib natija! 🎉"
                    if score >= 4
                    else "Yaxshi harakat! Xatolarni o‘rganib, yana urinib ko‘ring. 💪"
                )
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_MENU,
        )
        return

    question, options, _ = questions[index]
    keyboard = [
        [InlineKeyboardButton(
            f"{chr(65 + i)}. {option}",
            callback_data=f"quizans_{i}",
        )]
        for i, option in enumerate(options)
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📝 *Savol {index + 1}/{len(questions)}*\n\n{question}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("quizcat_"):
        category = data.replace("quizcat_", "", 1)
        if category not in QUIZZES:
            return

        context.user_data["quiz"] = {
            "category": category,
            "index": 0,
            "score": 0,
            "user_id": query.from_user.id,
        }
        await query.edit_message_text("Test boshlandi! Omad tilayman. 🍀")
        await send_quiz_question(query.message.chat_id, context)
        return

    if data.startswith("quizans_"):
        quiz = context.user_data.get("quiz")
        if not quiz:
            await query.edit_message_text(
                "Bu test yakunlangan yoki bekor qilingan. /quiz buyrug‘ini bosing."
            )
            return

        choice = int(data.replace("quizans_", "", 1))
        questions = QUIZZES[quiz["category"]]["questions"]
        index = quiz["index"]

        if index >= len(questions):
            return

        _, options, correct = questions[index]
        if choice == correct:
            quiz["score"] += 1
            result = "✅ To‘g‘ri javob!"
        else:
            result = f"❌ Noto‘g‘ri. To‘g‘ri javob: {options[correct]}"

        quiz["index"] += 1
        await query.edit_message_text(result)
        await send_quiz_question(query.message.chat_id, context)


# =========================
# 6. USTOZLAR
# =========================

async def become_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["flow"] = "teacher"
    context.user_data["teacher_form"] = {}
    context.user_data["teacher_step"] = 0

    await update.message.reply_text(
        "👨‍🏫 Ustoz sifatida ro‘yxatdan o‘tish.\n\n"
        "1/4. Ism-familiyangizni yuboring.\n"
        "Bekor qilish uchun /cancel."
    )


async def teachers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute(
            "SELECT name, subject, experience, contact "
            "FROM teachers WHERE status='approved' ORDER BY name"
        ).fetchall()

    if not rows:
        await update.message.reply_text(
            "Hozircha tasdiqlangan ustozlar ro‘yxati bo‘sh."
        )
        return

    for name, subject, experience, contact in rows:
        await update.message.reply_text(
            f"👨‍🏫 {name}\n"
            f"📚 Fan: {subject}\n"
            f"💼 Tajriba: {experience}\n"
            f"📞 Aloqa: {contact}"
        )


async def teacher_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("Bu amal faqat administrator uchun.")
        return

    parts = query.data.split("_")
    if len(parts) != 3:
        return

    action, teacher_id = parts[1], parts[2]
    if action not in ("approve", "reject"):
        return

    status = "approved" if action == "approve" else "rejected"

    with db() as conn:
        row = conn.execute(
            "SELECT user_id, name FROM teachers WHERE id=?",
            (teacher_id,),
        ).fetchone()

        if not row:
            await query.edit_message_text("Ariza topilmadi.")
            return

        conn.execute(
            "UPDATE teachers SET status=? WHERE id=?",
            (status, teacher_id),
        )

    user_id, name = row

    if action == "approve":
        message = "Tabriklaymiz! Ustozlik arizangiz administrator tomonidan tasdiqlandi."
    else:
        message = "Ustozlik arizangiz hozircha tasdiqlanmadi."

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
    except Exception:
        logger.warning("Ustozga xabar yuborilmadi: %s", user_id)

    await query.edit_message_text(
        f"{name} arizasi: {status}."
    )


# =========================
# 7. VIDEO DARSLIKLAR
# =========================

async def lessons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute(
            "SELECT id, title FROM lessons ORDER BY id DESC"
        ).fetchall()

    if not rows:
        await update.message.reply_text(
            "Hozircha video darsliklar yo‘q.\n"
            "Yangi darsliklar keyinroq qo‘shiladi."
        )
        return

    keyboard = [
        [InlineKeyboardButton(title, callback_data=f"lesson_{lesson_id}")]
        for lesson_id, title in rows
    ]

    await update.message.reply_text(
        "📚 Kerakli darslikni tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def lesson_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        lesson_id = int(query.data.replace("lesson_", "", 1))
    except ValueError:
        return

    with db() as conn:
        row = conn.execute(
            "SELECT title, url, file_id FROM lessons WHERE id=?",
            (lesson_id,),
        ).fetchone()

    if not row:
        await query.message.reply_text("Darslik topilmadi.")
        return

    title, url, file_id = row

    if file_id:
        await context.bot.send_video(
            chat_id=query.message.chat_id,
            video=file_id,
            caption=title,
        )
    elif url:
        await query.message.reply_text(f"🎥 {title}\n{url}")
    else:
        await query.message.reply_text("Bu darslikda video yoki havola mavjud emas.")


async def handle_admin_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    if not is_admin(user.id):
        return

    caption = message.caption or ""
    if not caption.upper().startswith("DARS:"):
        await message.reply_text(
            "Videoni saqlash uchun izohini quyidagicha yozing:\n"
            "DARS: Ingliz tili — Present Perfect"
        )
        return

    title = caption[5:].strip()
    if not title:
        await message.reply_text("Dars nomini ham yozing.")
        return

    with db() as conn:
        conn.execute(
            "INSERT INTO lessons (title, file_id) VALUES (?, ?)",
            (title, message.video.file_id),
        )

    await message.reply_text(f"✅ “{title}” darsligi saqlandi.")


# =========================
# 8. ADMINISTRATOR
# =========================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bu buyruq faqat administrator uchun.")
        return

    with db() as conn:
        users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM teachers WHERE status='pending'"
        ).fetchone()[0]
        lesson_count = conn.execute(
            "SELECT COUNT(*) FROM lessons"
        ).fetchone()[0]
        quiz_count = conn.execute(
            "SELECT COUNT(*) FROM quiz_results"
        ).fetchone()[0]

        applications = conn.execute(
            "SELECT id, user_id, name, subject, experience, contact "
            "FROM teachers WHERE status='pending' ORDER BY id"
        ).fetchall()

    await update.message.reply_text(
        "🛠️ *Edu AI administrator paneli*\n\n"
        f"👥 Foydalanuvchilar: {users_count}\n"
        f"⏳ Kutilayotgan ustoz arizalari: {pending}\n"
        f"🎥 Darsliklar: {lesson_count}\n"
        f"📝 Ishlangan testlar: {quiz_count}\n\n"
        "Dars qo‘shish: /addlesson Nomi | https://havola\n"
        "Xabar tarqatish: /broadcast Xabar matni\n"
        "Telegram videosini saqlash: izohga DARS: dars nomi yozing.",
        parse_mode=ParseMode.MARKDOWN,
    )

    for row in applications:
        teacher_id, user_id, name, subject, experience, contact = row

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Tasdiqlash",
                    callback_data=f"teacher_approve_{teacher_id}",
                ),
                InlineKeyboardButton(
                    "❌ Rad etish",
                    callback_data=f"teacher_reject_{teacher_id}",
                ),
            ]
        ])

        await update.message.reply_text(
            f"⏳ *Yangi ustoz arizasi*\n\n"
            f"ID: {teacher_id}\n"
            f"Foydalanuvchi: {user_id}\n"
            f"Ism: {name}\n"
            f"Fan: {subject}\n"
            f"Tajriba: {experience}\n"
            f"Aloqa: {contact}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )


async def add_lesson_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bu amal faqat administrator uchun.")
        return

    raw = " ".join(context.args)
    if "|" not in raw:
        await update.message.reply_text(
            "Format:\n/addlesson Ingliz tili darsi | https://example.com"
        )
        return

    title, url = [part.strip() for part in raw.split("|", 1)]

    if not title or not url.startswith(("https://", "http://")):
        await update.message.reply_text("Dars nomi va to‘g‘ri http/https havola kiriting.")
        return

    with db() as conn:
        conn.execute(
            "INSERT INTO lessons (title, url) VALUES (?, ?)",
            (title, url),
        )

    await update.message.reply_text(f"✅ “{title}” darsligi qo‘shildi.")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bu amal faqat administrator uchun.")
        return

    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(
            "Foydalanish: /broadcast Hammaga yuboriladigan xabar"
        )
        return

    with db() as conn:
        user_ids = [
            row[0] for row in conn.execute(
                "SELECT user_id FROM users"
            ).fetchall()
        ]

    sent = 0
    failed = 0

    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📣 Tarqatish tugadi.\n"
        f"Yuborildi: {sent}\n"
        f"Yuborilmadi: {failed}"
    )


# =========================
# 9. MATNLI XABARLAR
# =========================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = update.effective_user
    text = message.text.strip()

    save_user(user)

    if text == "ℹ️ Yordam":
        await help_command(update, context)
        return

    if text == "🤖 AI o‘qituvchi":
        context.user_data["flow"] = "ai"
        await message.reply_text(
            "Savolingizni yozing. Mavzuni tushuntirib beraman.\n"
            "Asosiy menyuga qaytish uchun /start."
        )
        return

    if text == "📝 Test ishlash":
        await quiz_command(update, context)
        return

    if text == "👨‍🏫 Ustozlar":
        await teachers_command(update, context)
        return

    if text == "📚 Video darsliklar":
        await lessons_command(update, context)
        return

    if text == "➕ Ustoz bo‘lish":
        await become_teacher(update, context)
        return

    if context.user_data.get("flow") == "teacher":
        form = context.user_data.setdefault("teacher_form", {})
        step = context.user_data.get("teacher_step", 0)

        if step == 0:
            form["name"] = text
            context.user_data["teacher_step"] = 1
            await message.reply_text("2/4. Qaysi fandan dars berasiz?")
            return

        if step == 1:
            form["subject"] = text
            context.user_data["teacher_step"] = 2
            await message.reply_text("3/4. Tajribangizni yozing (masalan, 2 yil).")
            return

        if step == 2:
            form["experience"] = text
            context.user_data["teacher_step"] = 3
            await message.reply_text(
                "4/4. Aloqa ma’lumotingizni yuboring "
                "(telefon raqam yoki Telegram username)."
            )
            return

        if step == 3:
            form["contact"] = text

            with db() as conn:
                cursor = conn.execute(
                    "INSERT INTO teachers "
                    "(user_id, name, subject, experience, contact, status) "
                    "VALUES (?, ?, ?, ?, ?, 'pending')",
                    (
                        user.id,
                        form["name"],
                        form["subject"],
                        form["experience"],
                        form["contact"],
                    ),
                )
                teacher_id = cursor.lastrowid

            context.user_data.pop("flow", None)
            context.user_data.pop("teacher_form", None)
            context.user_data.pop("teacher_step", None)

            await message.reply_text(
                "✅ Ma’lumotlaringiz administratorga yuborildi. "
                "Tasdiqlangandan keyin ustozlar ro‘yxatida ko‘rinasiz.",
                reply_markup=MAIN_MENU,
            )

            if ADMIN_ID:
                try:
                    keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                "✅ Tasdiqlash",
                                callback_data=f"teacher_approve_{teacher_id}",
                            ),
                            InlineKeyboardButton(
                                "❌ Rad etish",
                                callback_data=f"teacher_reject_{teacher_id}",
                            ),
                        ]
                    ])
                    await context.bot.send_message(
                        chat_id=int(ADMIN_ID),
                        text=(
                            "👨‍🏫 Yangi ustoz arizasi\n\n"
                            f"ID: {teacher_id}\n"
                            f"Ism: {form.get('name', '')}\n"
                            f"Fan: {form.get('subject', '')}\n"
                            f"Tajriba: {form.get('experience', '')}\n"
                            f"Aloqa: {form.get('contact', '')}\n"
                            f"Telegram ID: {user.id}"
                        ),
                        reply_markup=keyboard,
                    )
                except Exception:
                    logger.exception("Administratorga ariza yuborilmadi")

            return

    if context.user_data.get("flow") == "ai" or not context.user_data.get("flow"):
        await ask_ai(update, context)
        return

    await message.reply_text(
        "Menyudan bo‘lim tanlang yoki /start buyrug‘ini yuboring.",
        reply_markup=MAIN_MENU,
    )


# =========================
# 10. XATOLARNI QAYD ETISH
# =========================

async def error_handler(update, context):
    logger.error(
        "Kutilmagan xatolik: %s",
        context.error,
        exc_info=context.error,
    )


# =========================
# 11. BOTNI ISHGA TUSHIRISH
# =========================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi. FadeHost Environment ni tekshiring.")

    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY topilmadi. FadeHost Environment ni tekshiring.")

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("teachers", teachers_command))
    application.add_handler(CommandHandler("lessons", lessons_command))
    application.add_handler(CommandHandler("become_teacher", become_teacher))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("addlesson", add_lesson_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))

    application.add_handler(
        CallbackQueryHandler(quiz_callback, pattern=r"^quiz(cat|ans)_")
    )
    application.add_handler(
        CallbackQueryHandler(teacher_decision, pattern=r"^teacher_(approve|reject)_")
    )
    application.add_handler(
        CallbackQueryHandler(lesson_callback, pattern=r"^lesson_")
    )

    application.add_handler(
        MessageHandler(filters.VIDEO, handle_admin_video)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    application.add_error_handler(error_handler)

    logger.info("Edu AI ishga tushmoqda...")
    application.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
