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

    logger.info(
        "HTTP server started on port %s",
        PORT
    )

    server.serve_forever()


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.message:
        await update.message.reply_text(
            START_TEXT
        )


async def download_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    url = update.message.text.strip()

    if not url.startswith(
        ("https://", "http://")
    ):

        await update.message.reply_text(
            "🔗 Отправь мне ссылку на видео."
        )

        return


    status = await update.message.reply_text(
        "⏳ Скачиваю видео...\n\n"
        "Пожалуйста, подожди."
    )


    try:

        with tempfile.TemporaryDirectory() as temp_dir:

            output_template = str(
                Path(temp_dir) /
                "video.%(ext)s"
            )


            def download():

                options = {

                    "outtmpl": output_template,

                    "format": (
                        "bv*[height<=1080]+ba/"
                        "b[height<=1080]/"
                        "bv*+ba/b"
                    ),

                    "merge_output_format": "mp4",

                    "noplaylist": True,

                    "quiet": True,

                    "no_warnings": True,

                    "socket_timeout": 30,

                    "retries": 3,

                    "fragment_retries": 3,

                    "concurrent_fragment_downloads": 4,

                    "js_runtimes": {
                        "node": {}
                    },

                    "remote_components": [
                        "ejs:github"
                    ],
                }


                with yt_dlp.YoutubeDL(
                    options
                ) as ydl:

                    ydl.download([url])


            await asyncio.to_thread(
                download
            )


            files = [
                path
                for path in Path(temp_dir).iterdir()
                if path.is_file()
            ]


            if not files:

                raise RuntimeError(
                    "yt-dlp не создал файл видео."
                )


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


            if file_size > 49 * 1024 * 1024:

                await status.edit_text(
                    "❌ Видео слишком большое "
                    "для отправки через Telegram."
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
            "DOWNLOAD ERROR: %s",
            error
        )


        error_text = str(error)


        if not error_text:

            error_text = (
                "Неизвестная ошибка."
            )


        if len(error_text) > 700:

            error_text = (
                error_text[:700]
                + "..."
            )


        try:

            await status.edit_text(
                "❌ Ошибка скачивания:\n\n"
                f"{error_text}"
            )

        except Exception:

            pass


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "TELEGRAM ERROR:",
        exc_info=context.error
    )


def main():

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN не найден "
            "в Environment Variables Render."
        )


    web_thread = threading.Thread(
        target=start_web_server,
        daemon=True
    )

    web_thread.start()


    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )


    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


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
        "VIDEO DOWNLOADER BOT STARTED"
    )


    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":

    main()
