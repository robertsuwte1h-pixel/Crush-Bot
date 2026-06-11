import asyncio
import base64
import logging
import os
import re
import uuid
from io import BytesIO
from aiohttp import web
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

# In-memory token store  {token: {chat_id, crush_name, user_name, gender}}
tokens_store: dict = {}

# ── Startup file checks and fault-tolerant loading ──────────────────────────
_base_dir = os.path.dirname(__file__)


def _extract_gif_b64_from_html(filepath: str) -> str:
    """Extract base64 GIF data from an HTML file containing <img src='data:image/gif;base64,...'>."""
    if not os.path.isfile(filepath):
        logger.warning(f"[STARTUP] File NOT FOUND: {filepath}")
        return ""
    try:
        content = open(filepath, encoding="utf-8").read()
        match = re.search(r"data:image/gif;base64,([A-Za-z0-9+/=\s]+)", content)
        if match:
            b64_data = match.group(1).replace("\n", "").replace("\r", "").replace(" ", "")
            logger.info(f"[STARTUP] Extracted GIF from {os.path.basename(filepath)} ({len(b64_data)} chars)")
            return b64_data
        else:
            logger.warning(f"[STARTUP] No base64 GIF found in {filepath}")
            return ""
    except Exception as e:
        logger.error(f"[STARTUP] Failed to read {filepath}: {e}")
        return ""


# Load GIF base64 data from HTML wrapper files
HANDSOME_GIF_B64 = _extract_gif_b64_from_html(os.path.join(_base_dir, "handsome gif.html"))
CUTE_GIRL_GIF_B64 = _extract_gif_b64_from_html(os.path.join(_base_dir, "cute girl gif.html"))
YES_GIF_B64 = _extract_gif_b64_from_html(os.path.join(_base_dir, "After saying yes.html"))
CUTE_GIF_B64 = _extract_gif_b64_from_html(os.path.join(_base_dir, "cute.html"))
POPOS_GIF_B64 = _extract_gif_b64_from_html(os.path.join(_base_dir, "popos.html"))
PROPOSE_GIF_B64 = _extract_gif_b64_from_html(os.path.join(_base_dir, "propose.html"))

# Load Image.html template
_image_html_path = os.path.join(_base_dir, "Image.html")
IMAGE_HTML_TEMPLATE = ""
if os.path.isfile(_image_html_path):
    IMAGE_HTML_TEMPLATE = open(_image_html_path, encoding="utf-8").read()
    # Remove markdown code fence markers if present (file starts with ```html)
    IMAGE_HTML_TEMPLATE = re.sub(r'^```html\s*\n', '', IMAGE_HTML_TEMPLATE)
    IMAGE_HTML_TEMPLATE = re.sub(r'\n```\s*$', '', IMAGE_HTML_TEMPLATE)
    logger.info(f"[STARTUP] Image.html loaded OK ({len(IMAGE_HTML_TEMPLATE)} chars)")
else:
    logger.warning("[STARTUP] Image.html NOT FOUND")

logger.info(f"[STARTUP] YES_GIF available: {bool(YES_GIF_B64)}")
logger.info(f"[STARTUP] HANDSOME_GIF available: {bool(HANDSOME_GIF_B64)}")
logger.info(f"[STARTUP] CUTE_GIRL_GIF available: {bool(CUTE_GIRL_GIF_B64)}")

WAITING_FOR_GENDER = 1
WAITING_FOR_NAME = 2
WAITING_FOR_CRUSH_NAME = 3
WAITING_FOR_AFTER_HTML = 4

# ─────────────────────────── HTML generators ────────────────────────────────

def _generate_yes_card_html(crush_name: str, user_name: str) -> str:
    """Generate the Image.html scrapbook card with crush_name and user_name pre-filled.
    This is sent to the user as a document when crush says Yes."""
    html = IMAGE_HTML_TEMPLATE

    # Replace crushNameInput default value "Toma" with actual crush name
    html = html.replace(
        'id="crushNameInput" value="Toma"',
        f'id="crushNameInput" value="{crush_name}" readonly'
    )
    # Replace creatorNameInput default value "Shuvo" with actual user name
    html = html.replace(
        'id="creatorNameInput" value="Shuvo"',
        f'id="creatorNameInput" value="{user_name}" readonly'
    )
    # Replace crushNameDisplay text "Toma" with crush name
    html = html.replace(
        'id="crushNameDisplay" class="border-b-2 border-dotted border-rose-300 px-2 min-w-[60px] text-pink-600 font-bold italic">Toma</span>',
        f'id="crushNameDisplay" class="border-b-2 border-dotted border-rose-300 px-2 min-w-[60px] text-pink-600 font-bold italic">{crush_name}</span>'
    )
    # Replace creatorNameDisplay text "Shuvo" with user name
    html = html.replace(
        'id="creatorNameDisplay" class="bg-amber-100 text-amber-800 px-3 py-0.5 rounded-full font-bold">Shuvo</span>',
        f'id="creatorNameDisplay" class="bg-amber-100 text-amber-800 px-3 py-0.5 rounded-full font-bold">{user_name}</span>'
    )

    return html


def generate_html(crush_name: str, user_name: str, gender: str, token: str) -> str:
    """Generate the scrapbook HTML card using Image.html template with names pre-filled,
    gender-appropriate GIF, and Yes/No buttons with callback URL."""
    callback_url = f"{SERVER_URL}/yes?token={token}"

    # Select gender-appropriate GIF
    if gender == "\u099b\u09c7\u09b2\u09c7":  # ছেলে
        gender_gif_b64 = HANDSOME_GIF_B64
    else:  # মেয়ে
        gender_gif_b64 = CUTE_GIRL_GIF_B64

    # Start with Image.html template
    html = IMAGE_HTML_TEMPLATE

    # Replace crushNameInput default value "Toma" with actual crush name
    html = html.replace(
        'id="crushNameInput" value="Toma"',
        f'id="crushNameInput" value="{crush_name}" readonly'
    )
    # Replace creatorNameInput default value "Shuvo" with actual user name
    html = html.replace(
        'id="creatorNameInput" value="Shuvo"',
        f'id="creatorNameInput" value="{user_name}" readonly'
    )
    # Replace crushNameDisplay text "Toma" with crush name
    html = html.replace(
        'id="crushNameDisplay" class="border-b-2 border-dotted border-rose-300 px-2 min-w-[60px] text-pink-600 font-bold italic">Toma</span>',
        f'id="crushNameDisplay" class="border-b-2 border-dotted border-rose-300 px-2 min-w-[60px] text-pink-600 font-bold italic">{crush_name}</span>'
    )
    # Replace creatorNameDisplay text "Shuvo" with user name
    html = html.replace(
        'id="creatorNameDisplay" class="bg-amber-100 text-amber-800 px-3 py-0.5 rounded-full font-bold">Shuvo</span>',
        f'id="creatorNameDisplay" class="bg-amber-100 text-amber-800 px-3 py-0.5 rounded-full font-bold">{user_name}</span>'
    )

    # Build gender GIF section
    gender_gif_section = ""
    if gender_gif_b64:
        gender_gif_src = "data:image/gif;base64," + gender_gif_b64
        gender_label = "\U0001f468 Handsome Boy" if gender == "\u099b\u09c7\u09b2\u09c7" else "\U0001f469 Cute Girl"
        gender_gif_section = f'''
        <div style="text-align:center; margin: 15px 0;">
            <p style="font-size:12px; color:#888; margin-bottom:5px;">{gender_label}</p>
            <img src="{gender_gif_src}" alt="Gender GIF" style="width:180px; height:auto; border-radius:12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
        </div>'''

    # Build propose/popos/cute GIF decoration section
    decoration_gifs = ""
    gif_items = []
    if PROPOSE_GIF_B64:
        gif_items.append(("data:image/gif;base64," + PROPOSE_GIF_B64, "Propose"))
    if POPOS_GIF_B64:
        gif_items.append(("data:image/gif;base64," + POPOS_GIF_B64, "Love"))
    if CUTE_GIF_B64:
        gif_items.append(("data:image/gif;base64," + CUTE_GIF_B64, "Cute"))

    if gif_items:
        items_html = ""
        for src, alt in gif_items:
            items_html += f'<img src="{src}" alt="{alt}" style="width:100px; height:100px; object-fit:cover; border-radius:10px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">\n'
        decoration_gifs = f'''
        <div style="display:flex; justify-content:center; gap:10px; flex-wrap:wrap; margin: 15px 0;">
            {items_html}
        </div>'''

    # Build Yes/No section with dodging No button
    yes_no_section = f'''
    <!-- Yes/No Section -->
    <div id="yes-no-section" style="text-align:center; margin-top:20px; padding:20px; background:linear-gradient(135deg, #fff5f7, #ffe8f0); border-radius:16px; border:1px solid #fecdd3;">
        <h2 style="font-size:1.5rem; color:#f43f5e; font-family:'Pacifico',cursive; margin-bottom:8px;">Do you love me?</h2>
        <p style="color:#888; font-size:0.9rem; margin-bottom:16px;">\U0001f495 {crush_name} \U0001f495</p>
        <div style="display:flex; justify-content:center; gap:20px; position:relative;">
            <button id="yes-btn" onclick="handleYes()" style="background:#f43f5e; color:white; border:none; border-radius:50px; padding:12px 38px; font-size:1.05rem; font-weight:bold; cursor:pointer; box-shadow:0 5px 15px rgba(244,63,94,0.35); transition: transform 0.15s;">Yes \u2764\ufe0f</button>
            <button id="no-btn" style="background:#f43f5e; color:white; border:none; border-radius:50px; padding:12px 38px; font-size:1.05rem; font-weight:bold; cursor:pointer; box-shadow:0 5px 15px rgba(244,63,94,0.35); transition: transform 0.15s;">No</button>
        </div>
    </div>
    <div id="success-section" style="display:none; text-align:center; margin-top:20px; padding:20px;">
        <div style="font-size:3.5rem; animation: pulse 0.8s infinite alternate;">\u2764\ufe0f</div>
        <h2 style="font-size:1.6rem; color:#f43f5e; margin-top:10px; font-weight:800;">I knew it! \U0001f970</h2>
        <p style="color:#888; margin-top:8px; font-size:.95rem;">Love you, {crush_name}! \U0001f496</p>
    </div>
    <style>
        #no-btn.dodging {{
            position: fixed; border-radius: 50px; z-index: 100;
            transition: left 0.05s, top 0.05s;
        }}
        @keyframes pulse {{ from {{ transform: scale(1); }} to {{ transform: scale(1.25); }} }}
    </style>
    <script>
        const noBtn  = document.getElementById('no-btn');
        const yesBtn = document.getElementById('yes-btn');
        const yesNoSection    = document.getElementById('yes-no-section');
        const successSection2 = document.getElementById('success-section');
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
        noBtn.addEventListener('touchstart', function(e) {{ e.preventDefault(); startDodging(); }});
        noBtn.addEventListener('click',      startDodging);

        function handleYes() {{
            yesNoSection.style.display    = 'none';
            noBtn.style.display           = 'none';
            successSection2.style.display = 'block';

            var callbackUrl = '{callback_url}';
            var notified = false;

            try {{
                if (navigator.sendBeacon) {{
                    var sent = navigator.sendBeacon(callbackUrl);
                    if (sent) notified = true;
                }}
            }} catch(e) {{}}

            try {{
                var img = new Image();
                img.onerror = function() {{
                    try {{ fetch(callbackUrl, {{ mode: 'no-cors', cache: 'no-store' }}); }} catch(e2) {{}}
                }};
                img.src = callbackUrl;
            }} catch(e) {{}}

            if (!notified) {{
                try {{ fetch(callbackUrl, {{ mode: 'no-cors', cache: 'no-store' }}); }} catch(e) {{}}
            }}

            // Trigger love shower on yes
            if (typeof triggerLoveShower === 'function') triggerLoveShower();
        }}
    </script>'''

    # Insert gender GIF, decoration GIFs, and Yes/No section before closing </body>
    insert_content = f"{gender_gif_section}\n{decoration_gifs}\n{yes_no_section}"
    html = html.replace("</body>", f"{insert_content}\n</body>")

    return html


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

async def _send_html(update: Update, crush_name: str, bot_app: Application, user_name: str = "", gender: str = ""):
    token = str(uuid.uuid4())
    tokens_store[token] = {
        "chat_id": str(update.message.chat_id),
        "crush_name": crush_name,
        "user_name": user_name,
        "gender": gender,
    }

    html_bytes = generate_html(crush_name, user_name, gender, token).encode("utf-8")
    safe       = crush_name.replace(" ", "_").replace("/", "_")
    filename   = f"do_you_love_me_{safe}.html"

    await update.message.reply_document(
        document=html_bytes,
        filename=filename,
        caption=(
            f"\U0001f496 *{crush_name}* \u098f\u09b0 \u099c\u09a8\u09cd\u09af HTML \u09ab\u09be\u0987\u09b2 \u09a4\u09c8\u09b0\u09bf \u09b9\u09df\u09c7\u099b\u09c7!\n\n"
            "\U0001f4f2 \u09ab\u09be\u0987\u09b2\u099f\u09be \u09a1\u09be\u0989\u09a8\u09b2\u09cb\u09a1 \u0995\u09b0\u09c7 \u09a4\u09be\u0995\u09c7 \u09aa\u09be\u09a0\u09be\u09a8\u0964\n"
            "\u09b8\u09c7 \u09ac\u09cd\u09b0\u09be\u0989\u099c\u09be\u09b0\u09c7 \u0993\u09aa\u09c7\u09a8 \u0995\u09b0\u09b2\u09c7 \u0995\u09bf\u0989\u099f \u09aa\u09c7\u099c \u09a6\u09c7\u0996\u09ac\u09c7!\n\n"
            "\u09af\u09a6\u09bf *Yes* \u099a\u09be\u09aa\u09c7 \u2014 \u09a4\u09cb\u09ae\u09be\u09b0 \u0995\u09be\u099b\u09c7 notification \u0986\u09b8\u09ac\u09c7! \U0001f973\u2764\ufe0f"
        ),
        parse_mode="Markdown",
    )

    # Send the "After saying yes" GIF as a preview
    if YES_GIF_B64:
        try:
            gif_bytes = base64.b64decode(YES_GIF_B64)
            gif_buffer = BytesIO(gif_bytes)
            gif_buffer.name = "love_yes.gif"
            await update.message.reply_animation(
                animation=gif_buffer,
                caption=f"\U0001f495 {crush_name} Yes \u099a\u09be\u09aa\u09b2\u09c7 \u098f\u0987 GIF \u09a4\u09cb\u09ae\u09be\u0995\u09c7 \u09aa\u09be\u09a0\u09be\u09a8\u09cb \u09b9\u09ac\u09c7!",
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
            )
            logger.info(f"[_send_html] Yes GIF preview sent to user")
        except Exception as e:
            logger.error(f"[_send_html] Failed to send Yes GIF preview: {e}", exc_info=True)

    after_keyboard = ReplyKeyboardMarkup(
        [["\u0986\u09b0\u09c7\u0995\u099f\u09be \u09ac\u09be\u09a8\u09be\u0993 \U0001f504", "\u09ac\u09be\u09a4\u09bf\u09b2 \u274c"]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "\u0986\u09b0\u09c7\u0995\u099c\u09a8\u09c7\u09b0 \u099c\u09a8\u09cd\u09af \u09ac\u09be\u09a8\u09be\u09a4\u09c7 \u099a\u09be\u0987\u09b2\u09c7 \u09a8\u09bf\u099a\u09c7\u09b0 \u09ac\u09be\u099f\u09a8 \u099a\u09be\u09aa\u09c1\u09a8! \U0001f60a",
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
    user_name = context.user_data.get("user_name", "")
    gender = context.user_data.get("gender", "")
    await _send_html(update, crush_name, context.application, user_name=user_name, gender=gender)
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
        user_name = context.user_data.get("user_name", "")
        gender = context.user_data.get("gender", "")
        await _send_html(update, text, context.application, user_name=user_name, gender=gender)
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
            return web.Response(body=PIXEL_GIF, content_type="image/gif", headers=cors_headers)

        chat_id    = entry["chat_id"]
        crush_name = entry["crush_name"]
        user_name  = entry.get("user_name", "")
        logger.info(f"[/yes] Token valid. chat_id={chat_id}, crush_name={crush_name}")

        # Step 1: Send text notification (most important - must succeed)
        text_sent = False
        try:
            await bot_app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"\U0001f389 *{crush_name} said YES!* \U0001f389\n\n"
                    "\u2764\ufe0f \u09a4\u09cb\u09ae\u09be\u0995\u09c7 \u09ad\u09be\u09b2\u09cb\u09ac\u09be\u09b8\u09c7! \u098f\u0996\u09a8\u0987 \u0995\u09a5\u09be \u09ac\u09b2\u09cb! \U0001f495"
                ),
                parse_mode="Markdown",
            )
            text_sent = True
            logger.info(f"[/yes] Text notification sent successfully to chat_id={chat_id}")
        except Exception as e:
            logger.error(f"[/yes] FAILED to send text notification to chat_id={chat_id}: {e}")

        # Step 2: Send "After saying yes" GIF as animation
        if YES_GIF_B64:
            try:
                gif_bytes = base64.b64decode(YES_GIF_B64)
                gif_buffer = BytesIO(gif_bytes)
                gif_buffer.name = "love_yes.gif"
                await bot_app.bot.send_animation(
                    chat_id=chat_id,
                    animation=gif_buffer,
                    caption=f"\U0001f495 {crush_name} \U0001f495",
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=30,
                )
                logger.info(f"[/yes] Yes GIF animation sent to chat_id={chat_id}")
            except Exception as e:
                logger.error(f"[/yes] send_animation FAILED for chat_id={chat_id}: {e}", exc_info=True)
                if not text_sent:
                    try:
                        await bot_app.bot.send_message(
                            chat_id=chat_id,
                            text=f"{crush_name} said YES! \u2764\ufe0f",
                        )
                    except Exception as e3:
                        logger.error(f"[/yes] Even fallback message FAILED for chat_id={chat_id}: {e3}")
        else:
            logger.warning("[/yes] YES_GIF_B64 not available, only text notification sent")

        # Step 3: Send customized Image.html as document (scrapbook card with names)
        if IMAGE_HTML_TEMPLATE and user_name:
            try:
                customized_html = _generate_yes_card_html(crush_name, user_name)
                html_bytes = customized_html.encode("utf-8")
                safe_name = crush_name.replace(" ", "_").replace("/", "_")
                filename = f"{safe_name}_said_yes.html"
                await bot_app.bot.send_document(
                    chat_id=chat_id,
                    document=html_bytes,
                    filename=filename,
                    caption=f"\U0001f496 {crush_name} \u098f\u09b0 \u09b8\u09cd\u0995\u09cd\u09b0\u09cd\u09af\u09be\u09aa\u09ac\u09c1\u0995 \u0995\u09be\u09b0\u09cd\u09a1! \u09ac\u09cd\u09b0\u09be\u0989\u099c\u09be\u09b0\u09c7 \u0993\u09aa\u09c7\u09a8 \u0995\u09b0\u09c7 \u09a6\u09c7\u0996\u09c1\u09a8 \U0001f970",
                )
                logger.info(f"[/yes] Image.html document sent to chat_id={chat_id}")
            except Exception as e:
                logger.error(f"[/yes] Failed to send Image.html document: {e}", exc_info=True)

        return web.Response(body=PIXEL_GIF, content_type="image/gif", headers=cors_headers)

    @routes.post("/yes")
    async def handle_yes_post(request: web.Request) -> web.Response:
        """Handle POST requests from sendBeacon - delegates to same logic as GET."""
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
        user_name  = entry.get("user_name", "")
        logger.info(f"[/yes POST] Token valid. chat_id={chat_id}, crush_name={crush_name}")

        # Send text notification
        text_sent = False
        try:
            await bot_app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"\U0001f389 *{crush_name} said YES!* \U0001f389\n\n"
                    "\u2764\ufe0f \u09a4\u09cb\u09ae\u09be\u0995\u09c7 \u09ad\u09be\u09b2\u09cb\u09ac\u09be\u09b8\u09c7! \u098f\u0996\u09a8\u0987 \u0995\u09a5\u09be \u09ac\u09b2\u09cb! \U0001f495"
                ),
                parse_mode="Markdown",
            )
            text_sent = True
            logger.info(f"[/yes POST] Text notification sent to chat_id={chat_id}")
        except Exception as e:
            logger.error(f"[/yes POST] FAILED to send text: {e}")

        # Send "After saying yes" GIF as animation
        if YES_GIF_B64:
            try:
                gif_bytes = base64.b64decode(YES_GIF_B64)
                gif_buffer = BytesIO(gif_bytes)
                gif_buffer.name = "love_yes.gif"
                await bot_app.bot.send_animation(
                    chat_id=chat_id,
                    animation=gif_buffer,
                    caption=f"\U0001f495 {crush_name} \U0001f495",
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=30,
                )
                logger.info(f"[/yes POST] Yes GIF animation sent to chat_id={chat_id}")
            except Exception as e:
                logger.error(f"[/yes POST] send_animation FAILED: {e}", exc_info=True)
                if not text_sent:
                    try:
                        await bot_app.bot.send_message(chat_id=chat_id, text=f"{crush_name} said YES! \u2764\ufe0f")
                    except Exception as e3:
                        logger.error(f"[/yes POST] Even fallback FAILED: {e3}")
        else:
            logger.warning("[/yes POST] YES_GIF_B64 not available")

        # Send customized Image.html as document (scrapbook card with names)
        if IMAGE_HTML_TEMPLATE and user_name:
            try:
                customized_html = _generate_yes_card_html(crush_name, user_name)
                html_bytes = customized_html.encode("utf-8")
                safe_name = crush_name.replace(" ", "_").replace("/", "_")
                filename = f"{safe_name}_said_yes.html"
                await bot_app.bot.send_document(
                    chat_id=chat_id,
                    document=html_bytes,
                    filename=filename,
                    caption=f"\U0001f496 {crush_name} \u098f\u09b0 \u09b8\u09cd\u0995\u09cd\u09b0\u09cd\u09af\u09be\u09aa\u09ac\u09c1\u0995 \u0995\u09be\u09b0\u09cd\u09a1! \u09ac\u09cd\u09b0\u09be\u0989\u099c\u09be\u09b0\u09c7 \u0993\u09aa\u09c7\u09a8 \u0995\u09b0\u09c7 \u09a6\u09c7\u0996\u09c1\u09a8 \U0001f970",
                )
                logger.info(f"[/yes POST] Image.html document sent to chat_id={chat_id}")
            except Exception as e:
                logger.error(f"[/yes POST] Failed to send Image.html document: {e}", exc_info=True)

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
