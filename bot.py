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
import asyncio
import tempfile
from pathlib import Path

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
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
    # Original handler shows success section and calls fetch to a Replit URL
    # New handler redirects to bot via deep link
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


async def generate_said_yes_image(crush_name: str, creator_name: str) -> bytes:
    """
    Generate a 'Said Yes' card image using Playwright.
    Takes a screenshot of the said_yes_template.html with names injected.
    Uses a unique temp file to avoid race conditions.
    """
    from playwright.async_api import async_playwright

    with open(SAID_YES_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    # Replace placeholders
    html_content = template.replace("{{CRUSH_NAME}}", crush_name)
    html_content = html_content.replace("{{CREATOR_NAME}}", creator_name)

    # Write to a unique temporary HTML file to avoid race conditions
    temp_fd, temp_path = tempfile.mkstemp(suffix=".html", prefix="said_yes_")
    temp_html = Path(temp_path)
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(html_content)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            page = await browser.new_page(viewport={"width": 600, "height": 700})
            await page.goto(f"file://{temp_html.resolve()}")
            await page.wait_for_timeout(2000)  # Wait for fonts and rendering

            # Screenshot the card element
            card = page.locator("#card")
            screenshot_bytes = await card.screenshot(type="png")
            await browser.close()
    finally:
        if temp_html.exists():
            temp_html.unlink()

    return screenshot_bytes


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

        # Generate the Said Yes image
        try:
            image_bytes = await generate_said_yes_image(crush_name, creator_name)

            # Send image to the original user
            from io import BytesIO

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
                    "(Image generation unavailable - "
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

    # Install playwright browsers and OS dependencies on first run if needed
    try:
        import subprocess

        subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True,
            timeout=120,
        )
        subprocess.run(
            ["playwright", "install-deps", "chromium"],
            capture_output=True,
            timeout=120,
        )
        logger.info("Playwright chromium installed/verified.")
    except Exception as e:
        logger.warning(f"Playwright install skipped: {e}")

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
