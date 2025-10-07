import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ChatAction
import google.generativeai as genai

import tempfile
from fpdf import FPDF
import docx
import markdown2
import PyPDF2

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

genai.configure(api_key=GEMINI_API_KEY)

# State tracking (can upgrade to Redis or Railway storage for advanced usage)
USER_STATE = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("1️⃣ Send job description", callback_data='job_desc')]
    ]
    await update.message.reply_text(
        "👋 Welcome to Resume AI!\n\nStep 1: Attach or send your target job description.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == 'job_desc':
        USER_STATE[user_id] = {"step": "waiting_job_desc"}
        await query.edit_message_text("📄 Please send or upload your job description (text, PDF, DOCX, or MD)")
    elif query.data == 'resume':
        USER_STATE[user_id]["step"] = "waiting_resume"
        await query.edit_message_text("📄 Now send your resume file (PDF, DOCX, TXT, or MD) or paste your text.")

async def handle_file_or_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    state = USER_STATE.get(user_id, {})
    step = state.get("step")

    file = update.message.document
    message_text = update.message.text

    # Helper: Extract text from uploaded file
    def extract_text_from_file(document):
        ext = document.file_name.lower().split('.')[-1]
        file_id = document.file_id
        file_path = context.bot.get_file(file_id).download_as_bytearray()
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp_file:
            tmp_file.write(file_path)
            tmp_file.flush()
            tmp_name = tmp_file.name

        if ext == "pdf":
            with open(tmp_name, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = " ".join(page.extract_text() or "" for page in reader.pages)
            return text
        elif ext == "docx":
            doc = docx.Document(tmp_name)
            return "\n".join([para.text for para in doc.paragraphs])
        elif ext == "md":
            with open(tmp_name, "r", encoding="utf-8") as f:
                md_content = f.read()
            return markdown2.markdown(md_content)
        elif ext == "txt":
            with open(tmp_name, "r", encoding="utf-8") as f:
                return f.read()
        else:
            return None

    if step == "waiting_job_desc":
        if file:
            job_desc_text = extract_text_from_file(file)
        else:
            job_desc_text = message_text

        if not job_desc_text or len(job_desc_text) < 20:
            await update.message.reply_text("Please send a valid job description (text or supported file).")
            return

        USER_STATE[user_id]["job_desc"] = job_desc_text
        USER_STATE[user_id]["step"] = "waiting_resume"
        await update.message.reply_text("✅ Job description received!\n\nStep 2: Now send/upload your resume (PDF, DOCX, TXT, MD, or paste text).", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📄 Upload/resume", callback_data='resume')]]))

    elif step == "waiting_resume":
        if file:
            resume_text = extract_text_from_file(file)
        else:
            resume_text = message_text

        if not resume_text or len(resume_text) < 30:
            await update.message.reply_text("Send a valid resume in supported format/text.")
            return

        USER_STATE[user_id]["resume"] = resume_text
        USER_STATE[user_id]["step"] = "optimizing"
        await update.message.reply_text("🚀 Optimizing your resume for this job…", parse_mode="Markdown")
        await optimize_and_send_pdf(update, context, user_id)

    else:
        await update.message.reply_text("Use /start to begin.")

async def optimize_and_send_pdf(update, context, user_id):
    job_desc = USER_STATE[user_id]["job_desc"]
    resume_txt = USER_STATE[user_id]["resume"]

    prompt = f"""You are a top resume optimization expert.\nHere is the target job description:\n{job_desc}\n\nHere is the existing resume:\n{resume_txt}\n\nRewrite the resume to be ATS-friendly, compelling, and tailored specifically for the job. Add or rewrite sections with metrics, action verbs, and professional formatting, maintaining factual accuracy. Output plain text (no code blocks).\n"""

    model = genai.GenerativeModel('gemini-1.5-flash')
    response = await asyncio.to_thread(model.generate_content, prompt)
    optimized_resume = response.text

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=12)
    for line in optimized_resume.split('\n'):
        pdf.multi_cell(0, 10, line)
    tmp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(tmp_pdf.name)

    # Send back as Document
    await update.message.reply_document(document=open(tmp_pdf.name, "rb"),
                                        filename="Optimized_Resume.pdf",
                                        caption="✅ Your optimized ATS-ready resume tailored for your job description 🎯")

    USER_STATE[user_id]["step"] = "done"

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.ALL, handle_file_or_text))
    application.run_polling()

if __name__ == "__main__":
    main()
