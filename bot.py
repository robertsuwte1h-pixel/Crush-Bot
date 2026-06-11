import asyncio
import base64
import logging
import os
import uuid
from io import BytesIO
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
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
logger.info(f"[STARTUP] SERVER_URL = {SERVER_URL}")
logger.info(f"[STARTUP] RAILWAY_PUBLIC_DOMAIN = '{_railway_domain}'")

# In-memory token store  {token: {chat_id, crush_name}}
tokens_store: dict = {}

# ── Startup file checks and fault-tolerant loading ──────────────────────────
_base_dir = os.path.dirname(__file__)

# Load GIF once at startup
_gif_path = os.path.join(_base_dir, "bear_gif_b64.txt")
if os.path.isfile(_gif_path):
    GIF_B64 = open(_gif_path).read().strip()
    logger.info(f"[STARTUP] bear_gif_b64.txt loaded OK ({len(GIF_B64)} chars)")
else:
    GIF_B64 = ""
    logger.warning("[STARTUP] bear_gif_b64.txt NOT FOUND - GIF will be missing")

# Load love image (PNG) as PIL Image template at startup
_love_img_path = os.path.join(_base_dir, "love_image_b64.txt")
LOVE_IMAGE_TEMPLATE = None
if os.path.isfile(_love_img_path):
    try:
        _love_img_b64 = open(_love_img_path).read().strip()
        LOVE_IMAGE_TEMPLATE = Image.open(BytesIO(base64.b64decode(_love_img_b64)))
        logger.info("[STARTUP] love_image_b64.txt loaded OK")
    except Exception as e:
        logger.error(f"[STARTUP] love_image_b64.txt load FAILED: {e}")
        LOVE_IMAGE_TEMPLATE = None
else:
    logger.warning("[STARTUP] love_image_b64.txt NOT FOUND - love image feature disabled")

# Load Bengali font for text overlay (with fallback to default font)
_font_path = os.path.join(_base_dir, "NotoSansBengali.ttf")
BENGALI_FONT = None
if os.path.isfile(_font_path):
    try:
        BENGALI_FONT = ImageFont.truetype(_font_path, 58)
        logger.info("[STARTUP] NotoSansBengali.ttf loaded OK")
    except Exception as e:
        logger.error(f"[STARTUP] NotoSansBengali.ttf load FAILED: {e}")
        BENGALI_FONT = None
else:
    logger.warning("[STARTUP] NotoSansBengali.ttf NOT FOUND")

# Fallback to PIL default font if truetype font unavailable
if BENGALI_FONT is None:
    try:
        BENGALI_FONT = ImageFont.load_default()
        logger.info("[STARTUP] Using PIL default font as fallback")
    except Exception as e:
        logger.error(f"[STARTUP] Even default font failed to load: {e}")
        BENGALI_FONT = None

logger.info(f"[STARTUP] Image generation available: {LOVE_IMAGE_TEMPLATE is not None and BENGALI_FONT is not None}")

# Text overlay settings
_TEXT_COLOR = (169, 49, 51)  # Pink/red color matching original text
_TEXT_Y_CENTER = 150  # Vertical center of the name text area (Y=117-183)
_BG_COVER_COLOR = (254, 240, 213)  # Warm cream background behind text
_BG_COVER_Y1 = 115  # Top of background cover area
_BG_COVER_Y2 = 185  # Bottom of background cover area


def generate_love_image(crush_name: str) -> BytesIO:
    """Generate love image with crush name drawn on it."""
    if LOVE_IMAGE_TEMPLATE is None:
        raise RuntimeError("Love image template not available")
    if BENGALI_FONT is None:
        raise RuntimeError("Font not available for text overlay")

    img = LOVE_IMAGE_TEMPLATE.copy()
    draw = ImageDraw.Draw(img)

    # Calculate text size and position (centered horizontally)
    bbox = BENGALI_FONT.getbbox(crush_name)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    img_width = img.size[0]

    # Center the text horizontally, place at the name text area vertically
    x = (img_width - text_width) // 2
    y = _TEXT_Y_CENTER - text_height // 2 - bbox[1]

    # Cover the original text area with cream background color
    bg_x1 = max(0, x - 10)
    bg_x2 = min(img_width, x + text_width + 10)
    draw.rectangle([bg_x1, _BG_COVER_Y1, bg_x2, _BG_COVER_Y2], fill=_BG_COVER_COLOR)

    # Draw the new crush name
    draw.text((x, y), crush_name, font=BENGALI_FONT, fill=_TEXT_COLOR)

    # Convert to RGB (JPEG doesn't support alpha) with white background
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Save as JPEG to BytesIO buffer (much smaller than PNG)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    buffer.name = "love.jpg"
    return buffer

WAITING_FOR_GENDER = 1
WAITING_FOR_NAME = 2
WAITING_FOR_CRUSH_NAME = 3
WAITING_FOR_AFTER_HTML = 4

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

        var callbackUrl = '{callback_url}';
        var notified = false;

        // Method 1: navigator.sendBeacon (most reliable for mobile/background)
        try {{
            if (navigator.sendBeacon) {{
                var sent = navigator.sendBeacon(callbackUrl);
                console.log('[YES] sendBeacon result:', sent);
                if (sent) notified = true;
            }}
        }} catch(e) {{
            console.warn('[YES] sendBeacon failed:', e);
        }}

        // Method 2: Image pixel (backup - works cross-origin)
        try {{
            var img = new Image();
            img.onload = function() {{
                console.log('[YES] Image callback succeeded');
            }};
            img.onerror = function() {{
                console.warn('[YES] Image callback failed, trying fetch...');
                // Method 3: fetch as last resort
                try {{
                    fetch(callbackUrl, {{ mode: 'no-cors', cache: 'no-store' }}).then(function() {{
                        console.log('[YES] fetch callback succeeded');
                    }}).catch(function(e) {{
                        console.error('[YES] fetch also failed:', e);
                    }});
                }} catch(e2) {{
                    console.error('[YES] fetch not available:', e2);
                }}
            }};
            img.src = callbackUrl;
        }} catch(e) {{
            console.warn('[YES] Image approach failed:', e);
        }}

        // Method 4: If sendBeacon was not available or failed, also try fetch
        if (!notified) {{
            try {{
                fetch(callbackUrl, {{ mode: 'no-cors', cache: 'no-store' }});
                console.log('[YES] fetch fired as additional backup');
            }} catch(e) {{
                console.warn('[YES] backup fetch failed:', e);
            }}
        }}
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
    after_keyboard = ReplyKeyboardMarkup(
        [["আরেকটা বানাও 🔄", "বাতিল ❌"]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "আরেকজনের জন্য বানাতে চাইলে নিচের বাটন চাপুন! 😊",
        reply_markup=after_keyboard,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gender_keyboard = ReplyKeyboardMarkup(
        [["ছেলে", "মেয়ে"]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "💕 *Do You Love Me? Bot* 💕\n\n"
        "আপনি ছেলে নাকি মেয়ে?",
        parse_mode="Markdown",
        reply_markup=gender_keyboard,
    )
    return WAITING_FOR_GENDER


async def receive_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gender = update.message.text.strip()
    if gender not in ("ছেলে", "মেয়ে"):
        gender_keyboard = ReplyKeyboardMarkup(
            [["ছেলে", "মেয়ে"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        )
        await update.message.reply_text(
            "❌ দয়া করে নিচের বাটন থেকে সিলেক্ট করুন:",
            reply_markup=gender_keyboard,
        )
        return WAITING_FOR_GENDER
    context.user_data["gender"] = gender
    await update.message.reply_text(
        "আপনার নাম কী?",
        reply_markup=ReplyKeyboardRemove(),
    )
    return WAITING_FOR_NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not 1 <= len(name) <= 50:
        await update.message.reply_text("❌ নাম ১–৫০ অক্ষরের মধ্যে হতে হবে। আবার চেষ্টা করুন:")
        return WAITING_FOR_NAME
    context.user_data["user_name"] = name
    await update.message.reply_text(
        f"ধন্যবাদ, *{name}*! 😊\n\n"
        "এখন আপনার crush/GF/BF এর নাম লিখুন:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return WAITING_FOR_CRUSH_NAME


async def receive_crush_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    crush_name = update.message.text.strip()
    if not 1 <= len(crush_name) <= 50:
        await update.message.reply_text("❌ নাম ১–৫০ অক্ষরের মধ্যে হতে হবে। আবার চেষ্টা করুন:")
        return WAITING_FOR_CRUSH_NAME
    await update.message.reply_text(
        f"⏳ *{crush_name}* এর জন্য HTML তৈরি হচ্ছে...",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    await _send_html(update, crush_name, context.application)
    return WAITING_FOR_AFTER_HTML


async def receive_after_html(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button press after HTML is sent."""
    text = update.message.text.strip()
    if text == "আরেকটা বানাও 🔄":
        await update.message.reply_text(
            "আপনার crush/GF/BF এর নাম লিখুন:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return WAITING_FOR_CRUSH_NAME
    elif text == "বাতিল ❌":
        await update.message.reply_text(
            "বাতিল হয়েছে! আবার শুরু করতে নিচের বাটন চাপুন 😊",
            reply_markup=ReplyKeyboardMarkup(
                [["Start 🚀"]],
                one_time_keyboard=True,
                resize_keyboard=True,
            ),
        )
        return ConversationHandler.END
    else:
        # Treat any other text as a new crush name
        if not 1 <= len(text) <= 50:
            await update.message.reply_text("❌ নাম ১–৫০ অক্ষরের মধ্যে হতে হবে। আবার চেষ্টা করুন:")
            return WAITING_FOR_AFTER_HTML
        await update.message.reply_text(
            f"⏳ *{text}* এর জন্য HTML তৈরি হচ্ছে...",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        await _send_html(update, text, context.application)
        return WAITING_FOR_AFTER_HTML


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "বাতিল হয়েছে! আবার শুরু করতে নিচের বাটন চাপুন 😊",
        reply_markup=ReplyKeyboardMarkup(
            [["Start 🚀"]],
            one_time_keyboard=True,
            resize_keyboard=True,
        ),
    )
    return ConversationHandler.END


async def any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages outside conversation - show Start button."""
    text = update.message.text.strip()

    # Handle "Start 🚀" button press - trigger the /start flow
    if text == "Start 🚀":
        return await cmd_start(update, context)

    start_keyboard = ReplyKeyboardMarkup(
        [["Start 🚀"]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "💕 *Do You Love Me? Bot*\n\nশুরু করতে নিচের বাটন চাপুন!",
        parse_mode="Markdown",
        reply_markup=start_keyboard,
    )


# ─────────────────────────── HTTP server (aiohttp) ──────────────────────────

def make_web_app(bot_app: Application) -> web.Application:
    routes = web.RouteTableDef()

    # 1x1 transparent GIF pixel (smallest valid GIF image)
    PIXEL_GIF = base64.b64decode(
        "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
    )

    @routes.get("/yes")
    async def handle_yes(request: web.Request) -> web.Response:
        token = request.rel_url.query.get("token", "")
        logger.info(f"[/yes] Received request with token: {token[:8]}...")
        entry = tokens_store.pop(token, None)

        cors_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }

        if not entry:
            logger.warning(f"[/yes] Token NOT FOUND in store. Token: {token}. "
                           f"Store has {len(tokens_store)} entries. "
                           "Possible causes: app restarted (in-memory store lost), "
                           "token already used, or invalid token.")
            # Return 1x1 pixel GIF even for invalid tokens (so Image() completes)
            return web.Response(body=PIXEL_GIF, content_type="image/gif", headers=cors_headers)

        chat_id    = entry["chat_id"]
        crush_name = entry["crush_name"]
        logger.info(f"[/yes] Token valid. chat_id={chat_id}, crush_name={crush_name}")

        # Step 1: Send text notification (most important - must succeed)
        text_sent = False
        try:
            await bot_app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"\ud83c\udf89 *{crush_name} said YES!* \ud83c\udf89\n\n"
                    "\u2764\ufe0f \u09a4\u09cb\u09ae\u09be\u0995\u09c7 \u09ad\u09be\u09b2\u09cb\u09ac\u09be\u09b8\u09c7! \u098f\u0996\u09a8\u0987 \u0995\u09a5\u09be \u09ac\u09b2\u09cb! \ud83d\udc95"
                ),
                parse_mode="Markdown",
            )
            text_sent = True
            logger.info(f"[/yes] Text notification sent successfully to chat_id={chat_id}")
        except Exception as e:
            logger.error(f"[/yes] FAILED to send text notification to chat_id={chat_id}: {e}")

        # Step 2: Send love image (optional - if this fails, text was already sent)
        try:
            photo_file = generate_love_image(crush_name)
            buffer_size = photo_file.getbuffer().nbytes
            logger.info(f"[/yes] Love image generated: {buffer_size} bytes for crush_name='{crush_name}'")
            photo_file.seek(0)  # Ensure buffer is at start before sending
            await bot_app.bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=f"\ud83d\udc95 {crush_name} \ud83d\udc95",
            )
            logger.info(f"[/yes] Love image sent successfully to chat_id={chat_id}")
        except Exception as e:
            logger.error(f"[/yes] FAILED to send love image to chat_id={chat_id}: {e}", exc_info=True)
            # If text also failed, try one more time with a simple message
            if not text_sent:
                try:
                    await bot_app.bot.send_message(
                        chat_id=chat_id,
                        text=f"{crush_name} said YES! \u2764\ufe0f",
                    )
                    logger.info(f"[/yes] Fallback plain text sent to chat_id={chat_id}")
                except Exception as e2:
                    logger.error(f"[/yes] Even fallback message FAILED for chat_id={chat_id}: {e2}")

        # Return 1x1 pixel GIF so the Image() request completes successfully
        return web.Response(body=PIXEL_GIF, content_type="image/gif", headers=cors_headers)

    @routes.post("/yes")
    async def handle_yes_post(request: web.Request) -> web.Response:
        """Handle POST requests from sendBeacon - delegates to same logic as GET."""
        # sendBeacon sends POST requests, so we handle it the same way
        token = request.rel_url.query.get("token", "")
        logger.info(f"[/yes POST] Received sendBeacon request with token: {token[:8]}...")
        entry = tokens_store.pop(token, None)

        cors_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }

        if not entry:
            logger.warning(f"[/yes POST] Token NOT FOUND in store. Token: {token}.")
            return web.Response(text="ok", headers=cors_headers)

        chat_id    = entry["chat_id"]
        crush_name = entry["crush_name"]
        logger.info(f"[/yes POST] Token valid. chat_id={chat_id}, crush_name={crush_name}")

        # Send text notification
        text_sent = False
        try:
            await bot_app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"\ud83c\udf89 *{crush_name} said YES!* \ud83c\udf89\n\n"
                    "\u2764\ufe0f \u09a4\u09cb\u09ae\u09be\u0995\u09c7 \u09ad\u09be\u09b2\u09cb\u09ac\u09be\u09b8\u09c7! \u098f\u0996\u09a8\u0987 \u0995\u09a5\u09be \u09ac\u09b2\u09cb! \ud83d\udc95"
                ),
                parse_mode="Markdown",
            )
            text_sent = True
            logger.info(f"[/yes POST] Text notification sent to chat_id={chat_id}")
        except Exception as e:
            logger.error(f"[/yes POST] FAILED to send text: {e}")

        # Send love image
        try:
            photo_file = generate_love_image(crush_name)
            photo_file.seek(0)
            await bot_app.bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=f"\ud83d\udc95 {crush_name} \ud83d\udc95",
            )
            logger.info(f"[/yes POST] Love image sent to chat_id={chat_id}")
        except Exception as e:
            logger.error(f"[/yes POST] FAILED to send love image: {e}", exc_info=True)
            if not text_sent:
                try:
                    await bot_app.bot.send_message(chat_id=chat_id, text=f"{crush_name} said YES! \u2764\ufe0f")
                except Exception as e2:
                    logger.error(f"[/yes POST] Even fallback FAILED: {e2}")

        return web.Response(text="ok", headers=cors_headers)

    @routes.get("/debug")
    async def handle_debug(request: web.Request) -> web.Response:
        """Debug endpoint to check server status and configuration."""
        import json
        debug_info = {
            "server_url": SERVER_URL,
            "tokens_count": len(tokens_store),
            "railway_domain": _railway_domain,
            "status": "ok",
        }
        return web.Response(
            text=json.dumps(debug_info, ensure_ascii=False, indent=2),
            content_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

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
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.Regex("^Start 🚀$"), cmd_start),
        ],
        states={
            WAITING_FOR_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gender)],
            WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            WAITING_FOR_CRUSH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_crush_name)],
            WAITING_FOR_AFTER_HTML: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_after_html)],
        },
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
