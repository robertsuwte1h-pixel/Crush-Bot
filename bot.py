"""
Telegram Crush Bot - Generates a "Do you love me?" card and handles Yes responses.

Flow:
1. User starts the bot and provides their crush's name
2. Bot generates a personalized HTML file with the crush's name
3. User sends the HTML file to their crush
4. Crush clicks "Yes" -> redirected to bot via deep link
5. Bot generates a "Said Yes" scrapbook card image and sends it to the original user

Environment Variables:
    BOT_TOKEN: Telegram Bot Token from @BotFather
    BOT_USERNAME: Bot username (without @) for deep link generation
    ADMIN_USER_ID: Telegram user ID allowed to use /admin (optional, if unset admin is open)
"""

import os
import re
import json
import logging
import tempfile
from pathlib import Path
from io import BytesIO

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from PIL import Image, ImageDraw, ImageFont

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Bot configuration
# Reads from environment variable; fallback token for Railway if env var is not set
BOT_TOKEN = os.environ.get(
    "BOT_TOKEN", "8735896207:AAFfHdjeoJH8O7MBCW4AFs46rOW7TMkcPwI"
)
BOT_USERNAME = os.environ.get("BOT_USERNAME", "your_bot_username")
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID", "")

# Conversation states
ASKING_NAME = 0

# Data storage file
DATA_FILE = "user_data.json"

# Template paths
TEMPLATE_PATH = Path(__file__).parent / "do_you_love_me_Crush name.html"
SAID_YES_TEMPLATE_PATH = Path(__file__).parent / "said_yes_template.html"


def load_user_data() -> dict:
    """Load user data from JSON file."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_user_data(data: dict) -> None:
    """Save user data to JSON file atomically using temp-file-then-rename."""
    temp_fd, temp_path = tempfile.mkstemp(
        suffix=".json", prefix="user_data_", dir=Path(DATA_FILE).parent or "."
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, DATA_FILE)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def get_user_data() -> dict:
    """Get all user data."""
    return load_user_data()


def set_user_entry(user_id: str, entry: dict) -> None:
    """Set a user entry in data store."""
    data = load_user_data()
    data[user_id] = entry
    save_user_data(data)


def generate_love_html(crush_name: str, user_id: int) -> str:
    """
    Generate personalized 'Do you love me?' HTML content.
    Replaces the crush name and Yes button action with a deep link.
    """
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Replace the name in the .name-tag element
    # The emoji is U+1F495 (two hearts)
    heart_emoji = "\U0001f495"
    html_content = html_content.replace(
        f"{heart_emoji} Nai {heart_emoji}",
        f"{heart_emoji} {crush_name} {heart_emoji}",
    )

    # Replace the Yes button click handler using regex
    deep_link = f"https://t.me/{BOT_USERNAME}?start=yes_{user_id}"

    new_yes_handler = f"""    yesBtn.addEventListener('click', () => {{
        quizSection.style.display = 'none';
        noBtn.style.display = 'none';
        successSection.style.display = 'flex';
        // Redirect to bot
        window.location.href = '{deep_link}';
    }});"""

    # Use regex to match the yesBtn click handler regardless of whitespace/URL changes
    html_content = re.sub(
        r"yesBtn\.addEventListener\('click',\s*\(\)\s*=>\s*\{.*?\}\);",
        new_yes_handler.strip(),
        html_content,
        flags=re.DOTALL,
    )

    return html_content


def generate_said_yes_image(crush_name: str, creator_name: str) -> bytes:
    """
    Generate a 'Said Yes' card image using Pillow (PIL).
    Creates a beautiful scrapbook-style card with the crush name and creator name.
    No browser or Playwright needed - works on any server including Railway.
    """
    # Card dimensions
    width = 480
    height = 580

    # Create the card with a warm gradient background
    card = Image.new("RGB", (width, height), "#fff8f0")
    draw = ImageDraw.Draw(card)

    # Draw a subtle gradient effect
    for y in range(height):
        r = int(255 - (y / height) * 10)
        g = int(248 - (y / height) * 12)
        b = int(240 - (y / height) * 15)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Draw border
    draw.rounded_rectangle(
        [(3, 3), (width - 4, height - 4)],
        radius=24,
        outline="#f5e6d3",
        width=3,
    )

    # Try to load a nice font, fall back to default
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
        subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
        name_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
        by_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except (OSError, IOError):
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 38)
            subtitle_font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans.ttf", 30)
            name_font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 34)
            by_font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans.ttf", 20)
        except (OSError, IOError):
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            name_font = ImageFont.load_default()
            by_font = ImageFont.load_default()

    # Draw decorative hearts
    decorations = [
        (30, 20, "\u2764", 20, "#ffb6c1"),
        (420, 40, "\u2764", 16, "#ffc0cb"),
        (25, 480, "\u2764", 18, "#ffb6c1"),
        (430, 500, "\u2764", 22, "#ffc0cb"),
        (50, 100, "\u2728", 14, "#ffd700"),
    ]
    for x, y, char, size, color in decorations:
        try:
            deco_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
        except (OSError, IOError):
            deco_font = ImageFont.load_default()
        draw.text((x, y), char, fill=color, font=deco_font)

    # Draw avocado couple (simplified cute version)
    # Left avocado
    _draw_avocado(draw, 140, 160)
    # Right avocado
    _draw_avocado(draw, 290, 160)

    # Heart between avocados
    try:
        heart_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except (OSError, IOError):
        heart_font = ImageFont.load_default()
    draw.text((228, 200), "\u2764", fill="#ff0000", font=heart_font)

    # Draw crush name
    crush_bbox = draw.textbbox((0, 0), crush_name, font=name_font)
    crush_w = crush_bbox[2] - crush_bbox[0]
    draw.text(
        ((width - crush_w) // 2, 360),
        crush_name,
        fill="#e75480",
        font=name_font,
    )

    # Draw "Said Yes!" text
    said_yes_text = "Said Yes!"
    sy_bbox = draw.textbbox((0, 0), said_yes_text, font=subtitle_font)
    sy_w = sy_bbox[2] - sy_bbox[0]
    draw.text(
        ((width - sy_w) // 2, 405),
        said_yes_text,
        fill="#ff6b9d",
        font=subtitle_font,
    )

    # Draw "by creator_name" at the bottom
    by_text = f"by {creator_name}"
    by_bbox = draw.textbbox((0, 0), by_text, font=by_font)
    by_w = by_bbox[2] - by_bbox[0]
    draw.text(
        ((width - by_w) // 2, height - 50),
        by_text,
        fill="#999999",
        font=by_font,
    )

    # Add some sparkle/confetti dots for celebration
    import random
    random.seed(42)  # Fixed seed for consistent output
    confetti_colors = ["#ff6b9d", "#ffd700", "#87ceeb", "#98fb98", "#ffb6c1", "#dda0dd"]
    for _ in range(30):
        cx = random.randint(20, width - 20)
        cy = random.randint(20, height - 20)
        cr = random.randint(2, 4)
        color = random.choice(confetti_colors)
        draw.ellipse([(cx - cr, cy - cr), (cx + cr, cy + cr)], fill=color)

    # Save to bytes
    output = BytesIO()
    card.save(output, format="PNG", quality=95)
    output.seek(0)
    return output.getvalue()


def _draw_avocado(draw: ImageDraw.Draw, x: int, y: int) -> None:
    """Draw a cute avocado character at the given position."""
    # Body (green oval)
    draw.ellipse(
        [(x, y), (x + 70, y + 100)],
        fill="#8bc34a",
        outline="#689f38",
        width=2,
    )
    # Pit (brown circle)
    draw.ellipse(
        [(x + 20, y + 45), (x + 50, y + 80)],
        fill="#795548",
        outline="#5d4037",
        width=2,
    )
    # Eyes
    draw.ellipse([(x + 22, y + 25), (x + 30, y + 33)], fill="#333333")
    draw.ellipse([(x + 42, y + 25), (x + 50, y + 33)], fill="#333333")
    # Smile
    draw.arc(
        [(x + 26, y + 32), (x + 46, y + 48)],
        start=0,
        end=180,
        fill="#333333",
        width=2,
    )
    # Blush
    draw.ellipse([(x + 14, y + 35), (x + 24, y + 41)], fill="#ffb6c1")
    draw.ellipse([(x + 48, y + 35), (x + 58, y + 41)], fill="#ffb6c1")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start command and deep links."""
    args = context.args

    # Check for deep link: /start yes_USERID
    if args and args[0].startswith("yes_"):
        await handle_yes_callback(update, context, args[0])
        return ConversationHandler.END

    # Normal start - ask for crush name
    reply_keyboard = [["Cancel"]]
    await update.message.reply_text(
        "Hey! \ud83d\udc8c\n\n"
        "Tell me your crush/GF/BF's name and I'll create a special "
        "\"Do you love me?\" card for you!\n\n"
        "Just type their name below:",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard,
            one_time_keyboard=True,
            resize_keyboard=True,
        ),
    )
    return ASKING_NAME


async def handle_yes_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str
) -> None:
    """Handle when crush clicks Yes and arrives via deep link."""
    try:
        original_user_id = payload.replace("yes_", "")
        user_data = get_user_data()

        if original_user_id not in user_data:
            await update.message.reply_text(
                "Thanks for saying Yes! \u2764\ufe0f\n"
                "But I couldn't find the original request. "
                "The link may have expired."
            )
            return

        entry = user_data[original_user_id]
        crush_name = entry.get("crush_name", "Someone")
        creator_name = entry.get("user_name", "Someone")

        # Send acknowledgment to the crush
        await update.message.reply_text(
            f"Aww, you said YES! \ud83d\ude0d\u2764\ufe0f\n\n"
            f"Generating a beautiful card for {creator_name}...",
            reply_markup=ReplyKeyboardRemove(),
        )

        # Generate the Said Yes image using Pillow
        try:
            image_bytes = generate_said_yes_image(crush_name, creator_name)

            # Send image to the original user
            image_file = BytesIO(image_bytes)
            image_file.name = "said_yes.png"

            await context.bot.send_photo(
                chat_id=int(original_user_id),
                photo=image_file,
                caption=(
                    f"\ud83c\udf89 {crush_name} Said YES! \ud83c\udf89\n\n"
                    f"Congratulations! \u2764\ufe0f"
                ),
            )

            # Update status
            entry["status"] = "said_yes"
            entry["crush_telegram_name"] = (
                update.message.from_user.first_name
                if update.message.from_user
                else "Unknown"
            )
            set_user_entry(original_user_id, entry)

        except Exception as e:
            logger.error(f"Error generating image: {e}")
            # Fallback: send text notification
            await context.bot.send_message(
                chat_id=int(original_user_id),
                text=(
                    f"\ud83c\udf89 {crush_name} Said YES! \ud83c\udf89\n\n"
                    f"Congratulations! \u2764\ufe0f\n\n"
                    "(Image generation had an issue - "
                    "but the answer is still YES!)"
                ),
            )

    except Exception as e:
        logger.error(f"Error in yes callback: {e}")
        await update.message.reply_text(
            "Something went wrong, but thanks for saying Yes! \u2764\ufe0f"
        )


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the crush name input from user."""
    crush_name = update.message.text.strip()

    if crush_name.lower() == "cancel":
        await update.message.reply_text(
            "Cancelled! Use /start to try again.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name or "Someone"

    # Store user data
    set_user_entry(
        str(user_id),
        {
            "crush_name": crush_name,
            "user_name": user_name,
            "status": "waiting",
        },
    )

    await update.message.reply_text(
        f"\ud83d\udc96 Generating card for {crush_name}...\n"
        "Please wait a moment!",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Generate the HTML file
    try:
        html_content = generate_love_html(crush_name, user_id)

        # Save to temporary file and send
        output_path = Path(__file__).parent / f"love_card_{user_id}.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        with open(output_path, "rb") as doc_file:
            await update.message.reply_document(
                document=doc_file,
                filename=f"Do_you_love_me_{crush_name}.html",
                caption=(
                    f"\ud83d\udc8c Here's your card for {crush_name}!\n\n"
                    f"Send this file to your crush. When they open it "
                    f"and click 'Yes', I'll send you a special card!\n\n"
                    f"\u26a0\ufe0f Make sure they open it in a browser!"
                ),
            )

        # Clean up temp file
        if output_path.exists():
            output_path.unlink()

    except Exception as e:
        logger.error(f"Error generating HTML: {e}")
        await update.message.reply_text(
            "Sorry, something went wrong generating the card. "
            "Please try again with /start"
        )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text(
        "Cancelled! Use /start to try again.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Compact admin panel showing basic stats. Restricted to ADMIN_USER_ID."""
    # Authorization check
    if ADMIN_USER_ID:
        if str(update.message.from_user.id) != ADMIN_USER_ID:
            await update.message.reply_text(
                "You are not authorized to use this command.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

    user_data = get_user_data()
    total_users = len(user_data)
    waiting = sum(1 for v in user_data.values() if v.get("status") == "waiting")
    said_yes = sum(1 for v in user_data.values() if v.get("status") == "said_yes")

    admin_text = (
        "\ud83d\udcca Admin Panel\n"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"Total Cards: {total_users}\n"
        f"Waiting: {waiting}\n"
        f"Said Yes: {said_yes}\n"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
    )

    await update.message.reply_text(admin_text, reply_markup=ReplyKeyboardRemove())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help message."""
    await update.message.reply_text(
        "\ud83d\udc8c Crush Bot Help\n\n"
        "/start - Create a new love card\n"
        "/admin - View stats\n"
        "/help - Show this message\n\n"
        "How it works:\n"
        "1. Send /start and type your crush's name\n"
        "2. Send the generated HTML file to your crush\n"
        "3. When they click Yes, you get a special card!",
        reply_markup=ReplyKeyboardRemove(),
    )


def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error(
            "BOT_TOKEN environment variable not set! "
            "Please set it before running the bot."
        )
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler for getting crush name
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASKING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("help", help_command))

    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
