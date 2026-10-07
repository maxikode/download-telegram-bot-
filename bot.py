import os
import asyncio
import logging
import tempfile
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
        HealthHandler
    )

    logger.info("HTTP server started on port %s", PORT)

    server.serve_forever()


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.message:
        await update.message.reply_text(START_TEXT)


async def download_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()

    if not url.startswith(("https://", "http://")):
        await update.message.reply_text(
            "🔗 Отправь мне ссылку на видео."
        )
        return

    status = await update.message.reply_text(
        "⏳ Скачиваю видео...\n\n"
        "Это может занять некоторое время."
    )

    try:

        with tempfile.TemporaryDirectory() as temp_dir:

            output_template = str(
                Path(temp_dir) / "video.%(ext)s"
            )

            def download():

                options = {
                    "outtmpl": output_template,

                    # Лучшее доступное видео + лучшее аудио.
                    # Если отдельные потоки недоступны,
                    # используется готовый поток.
                    "format": (
                        "bv*[height<=1080]+ba/"
                        "b[height<=1080]/"
                        "bv*+ba/b"
                    ),

                    # Объединяем видео и аудио в MP4.
                    "merge_output_format": "mp4",

                    "noplaylist": True,

                    "quiet": True,

                    "no_warnings": True,

                    "socket_timeout": 30,

                    "retries": 3,

                    "fragment_retries": 3,

                    "concurrent_fragment_downloads": 4,

                    # Помогает yt-dlp использовать
                    # JavaScript challenge solving для YouTube.
                    "remote_components": {
                        "ejs": "github"
                    },
                }

                with yt_dlp.YoutubeDL(options) as ydl:
                    ydl.download([url])

            await asyncio.to_thread(download)

            files = [
                path
                for path in Path(temp_dir).iterdir()
                if path.is_file()
            ]

            if not files:
                raise RuntimeError(
                    "Видео не найдено после скачивания."
                )

            # После объединения FFmpeg обычно создаёт MP4.
            mp4_files = [
                path
                for path in files
                if path.suffix.lower() == ".mp4"
            ]

            if mp4_files:
                video_path = mp4_files[0]
            else:
                video_path = files[0]

            file_size = video_path.stat().st_size

            # Оставляем небольшой запас относительно
            # лимита Telegram Bot API.
            if file_size > 49 * 1024 * 1024:

                await status.edit_text(
                    "❌ Видео получилось слишком большим "
                    "для отправки через Telegram.\n\n"
                    "Попробуй видео меньшего размера."
                )

                return

            await status.edit_text(
                "📤 Видео скачано!\n"
                "Отправляю..."
            )

            with video_path.open("rb") as video:

                await update.message.reply_video(
                    video=video,
                    caption="🐶 Готово!",
                    read_timeout=180,
                    write_timeout=180,
                    connect_timeout=30,
                )

        try:
            await status.delete()
        except Exception:
            pass

    except Exception as error:

        logger.exception(
            "Ошибка скачивания: %s",
            error
        )

        try:

            await status.edit_text(
                "❌ Не получилось скачать видео.\n\n"
                "Возможные причины:\n"
                "• ссылка недоступна;\n"
                "• видео удалено или ограничено;\n"
                "• сайт временно не поддерживается;\n"
                "• видео слишком большое.\n\n"
                "Попробуй другую публичную ссылку."
            )

        except Exception:
            pass


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    logger.error(
        "Ошибка Telegram-бота:",
        exc_info=context.error
    )


def main():

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN не найден в Environment Variables Render."
        )

    # HTTP-сервер нужен Render,
    # чтобы Web Service считался работающим.
    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()

    # Создаём Telegram-приложение.
    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # /start
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # Все сообщения с HTTP/HTTPS ссылками.
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            download_video
        )
    )

    app.add_error_handler(
        error_handler
    )

    logger.info(
        "Telegram video downloader started!"
    )

    logger.info(
        "YouTube Shorts are supported."
    )

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
