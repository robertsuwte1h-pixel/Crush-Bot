import asyncio
import base64
import logging
import os
import uuid
from io import BytesIO
from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ╔══════════════════════════════════════════════════════╗
#  শুধু এখানে আপনার Telegram Bot Token বসান
BOT_TOKEN = "8735896207:AAHqwRYgE1eHumerhQ0sGW90QB9vHSfCCxc"
# ╚══════════════════════════════════════════════════════╝

# ── বাকি সব automatic ──────────────────────────────────
PORT = int(os.environ.get("PORT", "8080"))

_railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
_replit_domain  = os.environ.get("REPLIT_DOMAINS", "").split(",")[0].strip()
SERVER_URL = (
    f"https://{_railway_domain}" if _railway_domain else
    f"https://{_replit_domain}"  if _replit_domain  else
    f"http://localhost:{PORT}"
)
# ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# In-memory token store  {token: {chat_id, crush_name}}
tokens_store: dict = {}

# Load GIF once at startup
_gif_path = os.path.join(os.path.dirname(__file__), "bear_gif_b64.txt")
GIF_B64 = open(_gif_path).read().strip()

# Load love image (PNG) once at startup
_love_img_path = os.path.join(os.path.dirname(__file__), "love_image_b64.txt")
LOVE_IMAGE_B64 = open(_love_img_path).read().strip()

WAITING_FOR_NAME = 1

# ─────────────────────────── HTML generators ────────────────────────────────

def generate_html(crush_name: str, token: str) -> str:
    gif_src      = "data:image/gif;base64," + GIF_B64
    callback_url = f"{SERVER_URL}/yes?token={token}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Do you love me?</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh;
            background: #1e2235;
            font-family: 'Segoe UI', sans-serif;
            overflow: hidden;
        }}
        .card {{
            background: #fff; border-radius: 20px;
            padding: 40px 50px 45px; text-align: center;
            width: 340px; position: relative;
        }}
        .bears {{ position: relative; display: inline-block; margin-bottom: 18px; }}
        .speech-bubble {{
            position: absolute; top: -4px; right: 0;
            background: white; border: 1.5px solid #ccc;
            border-radius: 12px; padding: 4px 10px;
            font-size: 11px; color: #555; white-space: nowrap;
        }}
        .speech-bubble::after {{
            content: ''; position: absolute; bottom: -8px; left: 14px;
            border-width: 8px 6px 0; border-style: solid;
            border-color: #ccc transparent transparent;
        }}
        .speech-bubble::before {{
            content: ''; position: absolute; bottom: -6px; left: 15px;
            border-width: 7px 5px 0; border-style: solid;
            border-color: white transparent transparent; z-index: 1;
        }}
        h1 {{ font-size: 1.75rem; font-weight: 800; color: #222; margin-bottom: 8px; }}
        .name-tag {{ font-size: 1.1rem; color: #f06292; font-weight: 700; margin-bottom: 22px; }}
        .btn-container {{ display: flex; justify-content: center; gap: 20px; }}
        .btn {{
            background: #f06292; color: white; border: none;
            border-radius: 50px; padding: 12px 38px;
            font-size: 1.05rem; font-weight: bold; cursor: pointer;
            box-shadow: 0 5px 15px rgba(240,98,146,0.35);
            transition: transform 0.15s, background 0.15s;
        }}
        .btn:hover {{ background: #e91e8c; transform: scale(1.07); }}
        #no-btn.dodging {{
            position: fixed; border-radius: 50px; z-index: 100;
            transition: left 0.05s, top 0.05s;
        }}
        #success-section {{ display: none; flex-direction: column; align-items: center; }}
        #success-section h2 {{ font-size: 1.6rem; color: #f06292; margin-top: 10px; font-weight: 800; }}
        .heart-anim {{ font-size: 3.5rem; animation: pulse 0.8s infinite alternate; }}
        @keyframes pulse {{ from {{ transform: scale(1); }} to {{ transform: scale(1.25); }} }}
    </style>
</head>
<body>
<div class="card">
    <div id="quiz-section">
        <div class="bears">
            <img src="{gif_src}" alt="Cute Bears" style="width:190px;height:190px;object-fit:contain;">
            <div class="speech-bubble">Reply me</div>
        </div>
        <h1>Do you love me?</h1>
        <p class="name-tag">💕 {crush_name} 💕</p>
        <div class="btn-container">
            <button id="yes-btn" class="btn">Yes</button>
            <button id="no-btn" class="btn">No</button>
        </div>
    </div>
    <div id="success-section">
        <div class="heart-anim">❤️</div><br>
        <img src="{gif_src}" alt="Cute Bears" style="width:160px;height:160px;object-fit:contain;">
        <h2>I knew it! 🥰</h2>
        <p style="color:#888;margin-top:8px;font-size:.95rem;">Love you, {crush_name}! 💖</p>
    </div>
</div>
<script>
    const noBtn  = document.getElementById('no-btn');
    const yesBtn = document.getElementById('yes-btn');
    const quizSection    = document.getElementById('quiz-section');
    const successSection = document.getElementById('success-section');
    let isDodging = false;

    function startDodging() {{
        if (!isDodging) {{
            isDodging = true;
            const r = noBtn.getBoundingClientRect();
            noBtn.style.left  = r.left + 'px';
            noBtn.style.top   = r.top  + 'px';
            noBtn.style.width = noBtn.offsetWidth + 'px';
            noBtn.classList.add('dodging');
            document.body.appendChild(noBtn);
        }}
        const m = 60;
        const x = Math.floor(Math.random() * (window.innerWidth  - noBtn.offsetWidth  - m)) + m;
        const y = Math.floor(Math.random() * (window.innerHeight - noBtn.offsetHeight - m)) + m;
        noBtn.style.left = x + 'px';
        noBtn.style.top  = y + 'px';
    }}

    noBtn.addEventListener('mouseover',  startDodging);
    noBtn.addEventListener('touchstart', (e) => {{ e.preventDefault(); startDodging(); }});
    noBtn.addEventListener('click',      startDodging);

    yesBtn.addEventListener('click', () => {{
        quizSection.style.display    = 'none';
        noBtn.style.display          = 'none';
        successSection.style.display = 'flex';
        fetch('{callback_url}').catch(() => {{}});
    }});
</script>
</body>
</html>"""


def success_page(name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>💕 Yes!</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{
      display:flex; justify-content:center; align-items:center;
      min-height:100vh;
      background: linear-gradient(135deg,#ffe5ec,#ffc2d1);
      font-family:'Segoe UI',sans-serif;
    }}
    .card {{
      background:white; border-radius:24px; padding:50px 40px;
      text-align:center; box-shadow:0 20px 50px rgba(255,77,109,.2);
      max-width:360px; width:90%;
    }}
    .heart {{ font-size:5rem; animation:pulse .8s infinite alternate; display:block; }}
    @keyframes pulse {{ from{{transform:scale(1)}} to{{transform:scale(1.3)}} }}
    h1 {{ color:#ff4d6d; font-size:2rem; margin:20px 0 10px; }}
    p  {{ color:#888; font-size:1rem; }}
  </style>
</head>
<body>
  <div class="card">
    <span class="heart">❤️</span>
    <h1>{name} said YES! 🥰</h1>
    <p>এই মুহূর্তটা চিরকাল মনে থাকবে 💕</p>
  </div>
</body>
</html>"""


# ─────────────────────────── Telegram handlers ──────────────────────────────

async def _send_html(update: Update, crush_name: str, bot_app: Application):
    token = str(uuid.uuid4())
    tokens_store[token] = {"chat_id": str(update.message.chat_id), "crush_name": crush_name}

    html_bytes = generate_html(crush_name, token).encode("utf-8")
    safe       = crush_name.replace(" ", "_").replace("/", "_")
    filename   = f"do_you_love_me_{safe}.html"

    await update.message.reply_document(
        document=html_bytes,
        filename=filename,
        caption=(
            f"💖 *{crush_name}* এর জন্য HTML ফাইল তৈরি হয়েছে!\n\n"
            "📲 ফাইলটা ডাউনলোড করে তাকে পাঠান।\n"
            "সে ব্রাউজারে ওপেন করলে কিউট পেজ দেখবে!\n\n"
            "যদি *Yes* চাপে — তোমার কাছে notification আসবে! 🥳❤️"
        ),
        parse_mode="Markdown",
    )
    await update.message.reply_text("আরেকজনের জন্য বানাতে চাইলে নাম লিখুন! 😊")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💕 *Do You Love Me? Bot* 💕\n\n"
        "ক্রাশ বা GF/BF এর নাম লিখুন।\n"
        "কিউট HTML ফাইল বানিয়ে দেব — সে *Yes* দিলে notification পাবেন! 😄\n\n"
        "👇 এখন নামটি টাইপ করুন:",
        parse_mode="Markdown",
    )
    return WAITING_FOR_NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not 1 <= len(name) <= 50:
        await update.message.reply_text("❌ নাম ১–৫০ অক্ষরের মধ্যে হতে হবে। আবার চেষ্টা করুন:")
        return WAITING_FOR_NAME
    await update.message.reply_text(f"⏳ *{name}* এর জন্য HTML তৈরি হচ্ছে...", parse_mode="Markdown")
    await _send_html(update, name, context.application)
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("বাতিল। নাম লিখলেই আবার শুরু হবে।")
    return ConversationHandler.END


async def any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages outside conversation — treat text directly as name."""
    name = update.message.text.strip()
    if name.startswith("/"):
        await update.message.reply_text(
            "💕 *Do You Love Me? Bot*\n\nক্রাশের নাম লিখুন বা /start দিন!",
            parse_mode="Markdown",
        )
        return
    if not 1 <= len(name) <= 50:
        await update.message.reply_text("নাম ১–৫০ অক্ষরের মধ্যে হতে হবে।")
        return
    await update.message.reply_text(f"⏳ *{name}* এর জন্য HTML তৈরি হচ্ছে...", parse_mode="Markdown")
    await _send_html(update, name, context.application)


# ─────────────────────────── HTTP server (aiohttp) ──────────────────────────

def make_web_app(bot_app: Application) -> web.Application:
    routes = web.RouteTableDef()

    @routes.get("/yes")
    async def handle_yes(request: web.Request) -> web.Response:
        token = request.rel_url.query.get("token", "")
        entry = tokens_store.pop(token, None)

        if entry:
            chat_id    = entry["chat_id"]
            crush_name = entry["crush_name"]
            try:
                await bot_app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🎉 *{crush_name} said YES!* 🎉\n\n"
                        "❤️ তোমাকে ভালোবাসে! এখনই কথা বলো! 💕"
                    ),
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning(f"Telegram notify failed: {e}")
            # Send love image with crush name as caption
            try:
                image_data = base64.b64decode(LOVE_IMAGE_B64)
                photo_file = BytesIO(image_data)
                photo_file.name = "love.png"
                await bot_app.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_file,
                    caption=f"💕 {crush_name} 💕",
                )
            except Exception as e:
                logger.warning(f"Telegram photo send failed: {e}")
            return web.Response(text=success_page(crush_name), content_type="text/html")

        return web.Response(text=success_page("Someone special"), content_type="text/html")

    @routes.get("/health")
    async def health(_: web.Request) -> web.Response:
        return web.Response(text="OK")

    @routes.post("/webhook")
    async def webhook_handler(request: web.Request) -> web.Response:
        """Handle incoming Telegram webhook updates."""
        try:
            data = await request.json()
            update = Update.de_json(data, bot_app.bot)
            await bot_app.process_update(update)
        except Exception as e:
            logger.error(f"Webhook processing error: {e}")
        return web.Response(text="ok")

    app = web.Application()
    app.add_routes(routes)
    return app


# ─────────────────────────── Main entry point ───────────────────────────────

async def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN সেট করা হয়নি! bot.py এর উপরে BOT_TOKEN লিখুন।")
        return

    # Build Telegram bot
    bot_app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)]},
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )
    bot_app.add_handler(conv)
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_message))

    # Build HTTP server
    web_app = make_web_app(bot_app)
    runner  = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"HTTP server listening on port {PORT}")

    # Start bot - use webhook on Railway, polling for local dev
    await bot_app.initialize()
    await bot_app.start()

    if _railway_domain:
        # Railway deployment: use webhook mode
        webhook_url = f"https://{_railway_domain}/webhook"
        await bot_app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        logger.info(f"Webhook set: {webhook_url}")
    else:
        # Local development: use polling
        await bot_app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started in polling mode!")

    # Run forever
    try:
        await asyncio.Event().wait()
    finally:
        if not _railway_domain:
            await bot_app.updater.stop()
        else:
            await bot_app.bot.delete_webhook()
        await bot_app.stop()
        await bot_app.shutdown()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
