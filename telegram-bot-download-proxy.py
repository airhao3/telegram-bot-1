import logging
import re
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import yt_dlp
from dotenv import load_dotenv
import concurrent.futures
import time
import sys
import asyncio
import httpx

# 加载.env文件中的环境变量
load_dotenv()

# 将环境变量中的token赋值给TOKEN
#TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# 设置下载目录
DOWNLOAD_DIR = 'downloads'
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# 设置代理地址（根据你的实际代理地址进行修改）
PROXY = 'socks5://127.0.0.1:18888'

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# 创建线程池
executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started the bot")
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! Send me a video URL to download.",
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) requested help")
    await update.message.reply_text("Send me a video URL, and I'll download it for you!")

def is_url(text):
    """Check if the given text is a URL."""
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    return bool(url_pattern.match(text))

async def progress_hook(d, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if d['status'] == 'downloading':
        percent = d['_percent_str']
        speed = d['_speed_str']
        eta = d['_eta_str']
        await update.message.edit_text(f"Downloading: {percent} complete\nSpeed: {speed}\nETA: {eta}")
    elif d['status'] == 'finished':
        await update.message.edit_text("Download finished. Processing...")

async def download_video_task(url, update: Update, context: ContextTypes.DEFAULT_TYPE, max_retries=3):
    """Download the video from the provided URL with retries."""
    for attempt in range(max_retries):
        try:
            logger.info(f"Starting download attempt {attempt + 1} for URL: {url}")
            ydl_opts = {
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'logger': logger,
                'progress_hooks': [lambda d: asyncio.run_coroutine_threadsafe(progress_hook(d, update, context), asyncio.get_event_loop())],
                'proxy': PROXY,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                filename = os.path.splitext(filename)[0] + '.mp3'  # Change extension to mp3
            logger.info(f"Download completed successfully: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Download attempt {attempt + 1} failed: {str(e)}")
            if attempt == max_retries - 1:
                raise
            logger.info(f"Waiting 5 seconds before retry...")
            time.sleep(5)  # Wait for 5 seconds before retrying

async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle video download request."""
    user = update.effective_user
    message_text = update.message.text
    logger.info(f"Received message from user {user.id} ({user.username}): {message_text}")
    if is_url(message_text):
        status_message = await update.message.reply_text("Starting download. Please wait...")
        try:
            logger.info(f"Starting download process for URL: {message_text}")
            loop = asyncio.get_event_loop()
            filename = await loop.run_in_executor(executor, download_video_task, message_text, update, context)
            
            logger.info(f"Sending file to user: {filename}")
            # Send the downloaded file
            await update.message.reply_document(document=open(filename, 'rb'))
            
            logger.info(f"Deleting file: {filename}")
            # Delete the file after sending
            os.remove(filename)
            
            logger.info("Download and send process completed successfully")
            await status_message.edit_text("Download completed and file sent!")
        except Exception as e:
            logger.error(f"Failed to download: {str(e)}")
            await status_message.edit_text(f"Failed to download. Please try again later.")
    else:
        logger.warning(f"User {user.id} ({user.username}) sent invalid URL: {message_text}")
        await update.message.reply_text("This is not a valid URL. Please send a video URL.")


def main() -> None:
    """Start the bot."""
    logger.info("Starting the bot")
    
    # 使用代理创建 Application
    application = (
        Application.builder()
        .token(TOKEN)
        .http_version("1.1")
        .get_updates_http_version("1.1")
        .proxy(httpx.Proxy(PROXY))
        #.timeout(60.0)  # 增加超时时间
        .build()
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_video))
    
    logger.info("Bot is now polling for updates")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
