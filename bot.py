import os
import asyncio
import logging
import tempfile
import threading

from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import yt_dlp

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
PORT = int(os.environ.get("PORT", "10000"))

# Лимит отправки через стандартный Telegram Bot API.
MAX_VIDEO_MB = 49
MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024

START_TEXT = (
    "Привет! 👋\n\n"
    "Я бот по скачиванию видео из соцсетей. 📥\n\n"
    "Вы очень поддержите меня, если подпишитесь "
    "на канал @doglifebymax ❤️\n\n"
    "Заранее большое спасибо! 🐶\n\n"
    "Просто отправь мне ссылку на видео!"
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return


def start_web_server():
    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler,
    )
    logger.info("HTTP server started on port %s", PORT)
    server.serve_forever()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(START_TEXT)


def download_video_file(url: str, folder: str):
    output_template = str(Path(folder) / "video.%(ext)s")

    options = {
        "outtmpl": output_template,
        "format": (
            "best[height<=1080][ext=mp4]/"
            "best[height<=1080]/"
            "best[ext=mp4]/"
            "best"
        ),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
        "continuedl": True,
        "overwrites": True,

        # Поддержка JavaScript-решения для совместимых
        # версий yt-dlp и окружений.
        "js_runtimes": {
            "node": {}
        },
        "remote_components": [
            "ejs:github"
        ],
    }

    with yt_dlp.YoutubeDL(options) as downloader:
        downloader.download([url])

    files = [
        path
        for path in Path(folder).iterdir()
        if path.is_file()
        and path.name != "video.part"
    ]

    if not files:
        raise RuntimeError(
            "Сайт не предоставил видеофайл."
        )

    # Выбираем самый большой полученный файл.
    return max(files, key=lambda path: path.stat().st_size)


async def download_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        await update.message.reply_text(
            "🔗 Отправь корректную ссылку на видео."
        )
        return

    status = await update.message.reply_text(
        "⏳ Начинаю скачивание видео...\n\n"
        "Это может занять некоторое время."
    )

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = await asyncio.to_thread(
                download_video_file,
                url,
                temp_dir,
            )

            file_size = video_path.stat().st_size

            if file_size <= 0:
                raise RuntimeError(
                    "Скачанный файл пустой."
                )

            if file_size > MAX_VIDEO_BYTES:
                size_mb = file_size / (1024 * 1024)

                await status.edit_text(
                    "❌ Видео слишком большое для отправки.\n\n"
                    f"Размер файла: {size_mb:.1f} МБ.\n"
                    f"Максимум сейчас: {MAX_VIDEO_MB} МБ.\n\n"
                    "Стандартный Telegram Bot API не позволяет "
                    "отправлять ботом файлы больше 50 МБ."
                )
                return

            await status.edit_text(
                "📤 Видео скачано!\n"
                "Отправляю его в Telegram..."
            )

            suffix = video_path.suffix.lower()

            with video_path.open("rb") as video_file:
                if suffix == ".mp4":
                    await update.message.reply_video(
                        video=video_file,
                        caption="🐶 Готово!",
                        read_timeout=180,
                        write_timeout=180,
                        connect_timeout=30,
                        pool_timeout=30,
                        supports_streaming=True,
                    )
                else:
                    await update.message.reply_document(
                        document=video_file,
                        filename=video_path.name,
                        caption="🐶 Готово!",
                        read_timeout=180,
                        write_timeout=180,
                        connect_timeout=30,
                        pool_timeout=30,
                    )

        try:
            await status.delete()
        except Exception:
            pass

    except Exception as error:
        logger.exception("DOWNLOAD ERROR")

        error_text = str(error).strip()

        if len(error_text) > 900:
            error_text = error_text[:900] + "..."

        if (
            "Sign in to confirm you're not a bot" in error_text
            or "confirm you're not a bot" in error_text
        ):
            user_message = (
                "❌ YouTube не разрешил получить это видео "
                "с сервера Render.\n\n"
                "Попробуй позже или отправь ссылку с другого "
                "поддерживаемого сайта.\n\n"
                "Обновление yt-dlp не гарантирует устранения "
                "этого ограничения."
            )

        elif "Unsupported URL" in error_text:
            user_message = (
                "❌ Этот тип ссылки не поддерживается "
                "или сайт не распознан."
            )

        elif "Video unavailable" in error_text:
            user_message = (
                "❌ Видео недоступно. Возможно, оно удалено, "
                "приватное или ограничено самим сайтом."
            )

        elif "Requested format is not available" in error_text:
            user_message = (
                "❌ Не удалось получить доступный формат видео. "
                "Попробуй другую ссылку."
            )

        else:
            user_message = (
                "❌ Не удалось скачать видео.\n\n"
                "Подробности ошибки:\n"
                f"{error_text or 'Сайт не сообщил причину.'}"
            )

        try:
            await status.edit_text(user_message)
        except Exception:
            logger.exception("Не удалось отправить сообщение об ошибке")


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "TELEGRAM ERROR",
        exc_info=context.error,
    )


def main():
    if not TOKEN:
        raise RuntimeError(
            "Не найден BOT_TOKEN в Environment Variables Render."
        )

    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True,
    )
    web_thread.start()

    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            download_video,
        )
    )

    app.add_error_handler(error_handler)

    logger.info("VIDEO DOWNLOADER BOT STARTED")

    app.run_polling(
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
