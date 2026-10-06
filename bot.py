import os
import asyncio
import logging
import tempfile
from pathlib import Path

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


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.message:
        await update.message.reply_text(START_TEXT)


async def download_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()

    if not url.startswith(("https://", "http://")):
        await update.message.reply_text(
            "🔗 Отправь мне прямую ссылку на видео."
        )
        return

    status = await update.message.reply_text(
        "⏳ Скачиваю видео, пожалуйста, подожди..."
    )

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_template = str(
                Path(temp_dir) / "video.%(ext)s"
            )

            def download():
                options = {
                    "outtmpl": output_template,
                    "format": "best[ext=mp4]/best",
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "socket_timeout": 30,
                    "retries": 2,
                }

                with yt_dlp.YoutubeDL(options) as ydl:
                    ydl.download([url])

            await asyncio.to_thread(download)

            files = [
                path for path in Path(temp_dir).iterdir()
                if path.is_file()
            ]

            if not files:
                raise RuntimeError("Видео не найдено")

            video_path = files[0]

            # У Telegram есть ограничения на размер файлов.
            if video_path.stat().st_size > 49 * 1024 * 1024:
                await status.edit_text(
                    "❌ Видео слишком большое для отправки "
                    "этим способом. Попробуй видео меньшего размера."
                )
                return

            await status.edit_text("📤 Отправляю видео...")

            with video_path.open("rb") as video:
                await update.message.reply_video(
                    video=video,
                    caption="🐶 Готово! Приятного просмотра!",
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=30,
                )

        await status.delete()

    except Exception as error:
        logger.warning("Ошибка скачивания: %s", error)
        try:
            await status.edit_text(
                "❌ Не получилось скачать видео.\n\n"
                "Проверь ссылку или попробуй другое "
                "публичное видео. Некоторые сайты "
                "не поддерживаются или ограничивают скачивание."
            )
        except Exception:
            pass


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "Ошибка бота",
        exc_info=context.error,
    )


def main():
    if not TOKEN:
        raise RuntimeError(
            "Добавь BOT_TOKEN в переменные окружения Render"
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            download_video,
        )
    )
    app.add_error_handler(error_handler)

    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
