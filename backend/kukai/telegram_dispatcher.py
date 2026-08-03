"""Telegram dispatcher for KUKAI — L1/L2 Support alerts, alternate payments (SBP OCR), and churn interviews.

Built purely on top of `httpx` to avoid introducing external python-telegram-bot or aiogram dependencies.
Runs asynchronously and integrates directly with KUKAI's Database and LicenseManager.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from kukai.config import get_settings
from kukai.licensing.license_manager import LicenseManager
from kukai.storage.database import Database

logger = logging.getLogger("kukai.telegram_dispatcher")

# Constants provided by founder
BOT_TOKEN = "8581655882:AAFaBxfae77p69tdjSHPxjFwOlBd2WC_PtU"
FOUNDER_CHAT_ID = 819437499
BASE_TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# In-memory storage for pending payments to map callback queries back to users
# Schema: {payment_id: {"user_chat_id": int, "username": str, "amount": float}}
PENDING_PAYMENTS: dict[str, dict[str, Any]] = {}


class TelegramBotClient:
    """Lightweight async Telegram Bot API client using httpx."""

    def __init__(self, token: str = BOT_TOKEN):
        self.token = token
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.client.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        url = f"https://api.telegram.org/bot{self.token}/{endpoint}"
        try:
            response = await self.client.post(url, **kwargs)
            res_json = response.json()
            if not res_json.get("ok"):
                logger.error("Telegram API error: %s", res_json)
                return None
            return res_json.get("result")
        except Exception as e:
            logger.exception("HTTP request to Telegram failed: %s", e)
            return None

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> Any:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._request("POST", "sendMessage", json=payload)

    async def answer_callback_query(self, callback_query_id: str, text: str = "") -> Any:
        return await self._request("POST", "answerCallbackQuery", json={"callback_query_id": callback_query_id, "text": text})

    async def get_file_bytes(self, file_id: str) -> Optional[bytes]:
        """Download a file from Telegram by its file_id."""
        file_info = await self._request("POST", "getFile", json={"file_id": file_id})
        if not file_info:
            return None
        file_path = file_info.get("file_path")
        if not file_path:
            return None

        download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        try:
            res = await self.client.get(download_url)
            if res.status_code == 200:
                return res.content
            logger.error("Failed to download file from Telegram: status=%d", res.status_code)
            return None
        except Exception as e:
            logger.exception("Error downloading file from Telegram: %s", e)
            return None


async def analyze_receipt_with_gemini(photo_bytes: bytes, api_key: str) -> Optional[dict[str, Any]]:
    """Verify SBP receipt image using Google Gemini 1.5 Flash."""
    if not api_key:
        logger.error("Gemini API key is not configured. SBP verification disabled.")
        return None

    # Base64 encode the image
    b64_data = base64.b64encode(photo_bytes).decode("utf-8")

    # Gemini API Content endpoint
    # We use gemini-1.5-flash as it is lightning fast and free/cheap with vision support
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

    prompt = (
        "Ты — ИИ-бухгалтер. Твоя задача — детально проанализировать скриншот чека перевода (СБП, Тинькофф, Сбербанк, Альфа-Банк или СБП от любого банка).\n\n"
        "Выполни проверку по следующим критериям:\n"
        "1. Является ли изображение валидным чеком перевода (а не случайной картинкой).\n"
        "2. Получателем перевода должен быть Дмитрий Куклев, Дмитрий К. или близкие совпадения.\n"
        "3. Вытащи сумму перевода (число).\n"
        "4. Вытащи дату и время операции.\n"
        "5. Вытащи имя отправителя.\n"
        "6. Вытащи банк отправителя.\n\n"
        "Верни ответ STRICTLY в формате JSON с полями:\n"
        "{\n"
        '  "valid": true/false,\n'
        '  "amount": float (сумма перевода),\n'
        '  "sender": "имя отправителя",\n'
        '  "date": "дата и время перевода",\n'
        '  "bank": "название банка",\n'
        '  "reason": "краткое объяснение почему чек прошел или не прошел верификацию"\n'
        "}\n\n"
        "Никакого другого текста, разметки markdown или объяснений вне JSON возвращать НЕЛЬЗЯ."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": b64_data
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.error("Gemini API error: status=%d, response=%s", response.status_code, response.text)
                return None

            res_json = response.json()
            candidates = res_json.get("candidates", [])
            if not candidates:
                return None

            text_response = candidates[0]["content"]["parts"][0]["text"]
            # Parse strictly formatted JSON
            return json.loads(text_response.strip())
    except Exception as e:
        logger.exception("Error calling Gemini API for OCR: %s", e)
        return None


async def process_telegram_updates(
    bot: TelegramBotClient,
    db: Database,
    license_manager: LicenseManager,
    api_key: str,
):
    """Long polling loop for Telegram updates."""
    offset = 0
    logger.info("Telegram dispatcher bot started via Long Polling")

    # Notify founder on startup
    await bot.send_message(
        FOUNDER_CHAT_ID,
        "🟢 <b>ИИ-Операционка KUKAI запущена!</b>\n"
        "Диспетчер активен и готов принимать оплаты СБП, слать отчеты стабильности и отслеживать баги.",
    )

    while True:
        try:
            url = f"{BASE_TELEGRAM_URL}/getUpdates?offset={offset}&timeout=20"
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(url)
                if res.status_code != 200:
                    await asyncio.sleep(5)
                    continue

                res_json = res.json()
                if not res_json.get("ok"):
                    await asyncio.sleep(5)
                    continue

                updates = res_json.get("result", [])
                for update in updates:
                    offset = update["update_id"] + 1

                    # Handle Callback Queries (Inline buttons)
                    if "callback_query" in update:
                        await handle_callback_query(bot, license_manager, update["callback_query"])

                    # Handle incoming Messages
                    elif "message" in update:
                        await handle_message(bot, db, license_manager, api_key, update["message"])

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Error in Telegram updates loop: %s", e)
            await asyncio.sleep(5)


async def handle_message(
    bot: TelegramBotClient,
    db: Database,
    license_manager: LicenseManager,
    api_key: str,
    message: dict[str, Any],
):
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    username = message["from"].get("username", "")
    first_name = message["from"].get("first_name", "")

    # 1. Command /start
    if text == "/start":
        welcome_text = (
            f"Привет, {first_name}!\n\n"
            "Я <b>ИИ-ассистент KUKAI</b>. 🤖\n\n"
            "Здесь вы можете приобрести лицензионный ключ <b>KUKAI Pro</b> (автоматизация Revit + ценообразование VOR) напрямую.\n\n"
            "💵 <b>Стоимость тарифа Pro:</b> 4,900 руб. / месяц.\n\n"
            "💳 <b>Как оплатить через СБП:</b>\n"
            "1. Переведите <b>4,900 руб.</b> по номеру телефона:\n"
            "   <code>+7 (979) 797-97-97</code> (Получатель: <i>Дмитрий К.</i>)\n"
            "2. Сделайте <b>скриншот чека</b> об успешном переводе.\n"
            "3. <b>Отправьте скриншот чека прямо в этот чат</b>.\n\n"
            "Наш ИИ мгновенно верифицирует платеж и выдаст вам лицензионный ключ!"
        )
        await bot.send_message(chat_id, welcome_text)
        return

    # 2. Receipt image verification (Vision OCR)
    if "photo" in message:
        await bot.send_message(chat_id, "🔍 <i>ИИ-Бухгалтер анализирует ваш чек... Пожалуйста, подождите.</i>")

        # Take the highest resolution photo
        photo = message["photo"][-1]
        file_id = photo["file_id"]

        # Download bytes
        photo_bytes = await bot.get_file_bytes(file_id)
        if not photo_bytes:
            await bot.send_message(chat_id, "❌ Не удалось скачать файл. Попробуйте еще раз или отправьте картинкой.")
            return

        # Analyze with Gemini
        analysis = await analyze_receipt_with_gemini(photo_bytes, api_key)

        if not analysis:
            await bot.send_message(
                chat_id,
                "❌ Не удалось обработать чек через ИИ. Чек отправлен на ручную проверку фаундеру. Мы свяжемся с вами в ближайшее время!",
            )
            # Send to founder anyway for manual review
            payment_id = f"manual_{message['message_id']}"
            PENDING_PAYMENTS[payment_id] = {
                "user_chat_id": chat_id,
                "username": username or first_name,
                "amount": 4900.0,
            }

            markup = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Одобрить и выдать Pro", "callback_data": f"approve_pro:{payment_id}"},
                        {"text": "❌ Отклонить", "callback_data": f"reject:{payment_id}"}
                    ]
                ]
            }
            await bot.send_message(
                FOUNDER_CHAT_ID,
                f"⚠️ <b>Ручной платеж (ИИ не распознал):</b>\n"
                f"От: @{username} (ID: {chat_id})\n"
                f"Пожалуйста, проверьте чек выше в чате бота вручную.",
                reply_markup=markup,
            )
            return

        # Handle Gemini verification results
        if not analysis.get("valid"):
            reason = analysis.get("reason", "Реквизиты не совпадают или изображение не является чеком.")
            await bot.send_message(
                chat_id,
                f"⚠️ <b>Чек не прошел верификацию:</b>\n"
                f"<i>Причина: {reason}</i>\n\n"
                f"Если произошла ошибка, не переживайте! Ваш чек передан фаундеру для ручной проверки.",
            )
            # Send to founder for review
            payment_id = f"fail_{message['message_id']}"
            PENDING_PAYMENTS[payment_id] = {
                "user_chat_id": chat_id,
                "username": username or first_name,
                "amount": analysis.get("amount", 0.0),
            }
            markup = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Все равно выдать Pro", "callback_data": f"approve_pro:{payment_id}"},
                        {"text": "❌ Отклонить окончательно", "callback_data": f"reject:{payment_id}"}
                    ]
                ]
            }
            await bot.send_message(
                FOUNDER_CHAT_ID,
                f"🚨 <b>Подозрительный чек (ИИ забраковал):</b>\n"
                f"От: @{username} (ID: {chat_id})\n"
                f"Сумма: {analysis.get('amount')} руб.\n"
                f"Банк: {analysis.get('bank')}\n"
                f"Дата: {analysis.get('date')}\n"
                f"Вердикт ИИ: <i>{reason}</i>",
                reply_markup=markup,
            )
            return

        # SUCCESSFUL VERIFICATION!
        amount = analysis.get("amount", 4900.0)
        bank = analysis.get("bank", "СБП")
        date_str = analysis.get("date", "")
        sender_name = analysis.get("sender", "")

        await bot.send_message(
            chat_id,
            "✅ <b>Чек успешно распознан и верифицирован ИИ!</b>\n"
            "Запрос отправлен фаундеру для моментального подтверждения выпуска Pro-лицензии. Ожидайте!",
        )

        payment_id = f"sbp_{message['message_id']}"
        PENDING_PAYMENTS[payment_id] = {
            "user_chat_id": chat_id,
            "username": username or first_name,
            "amount": amount,
        }

        markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ ОДОБРИТЬ PRO", "callback_data": f"approve_pro:{payment_id}"},
                    {"text": "❌ ОТКЛОНИТЬ", "callback_data": f"reject:{payment_id}"}
                ]
            ]
        }

        await bot.send_message(
            FOUNDER_CHAT_ID,
            f"💰 <b>НОВЫЙ ПЛАТЕЖ СБП (Верифицирован ИИ):</b>\n"
            f"<b>Сумма:</b> {amount} руб.\n"
            f"<b>Отправитель:</b> {sender_name} (@{username})\n"
            f"<b>Банк:</b> {bank}\n"
            f"<b>Дата:</b> {date_str}\n"
            f"<b>ИИ-Статус:</b> 100% Валидный чек СБП Дмитрий К.",
            reply_markup=markup,
        )


async def handle_callback_query(
    bot: TelegramBotClient,
    license_manager: LicenseManager,
    callback_query: dict[str, Any],
):
    query_id = callback_query["id"]
    data = callback_query["data"]

    if ":" not in data:
        await bot.answer_callback_query(query_id, "Некорректные данные")
        return

    action, payment_id = data.split(":", 1)
    payment = PENDING_PAYMENTS.get(payment_id)

    if not payment:
        await bot.answer_callback_query(query_id, "Платеж устарел или уже обработан")
        return

    user_chat_id = payment["user_chat_id"]
    username = payment["username"]

    # 1. Approve Pro License
    if action == "approve_pro":
        try:
            # Generate new license key
            key = LicenseManager.generate_license_key()
            # Register in Postgres database via LicenseManager (duration = 30 days)
            await license_manager.register_license(
                key=key,
                tier="pro",
                days=30,
                name=f"TG: @{username}"
            )

            # Send license key to user
            user_text = (
                "🎉 <b>Ваш платеж успешно подтвержден!</b>\n\n"
                f"Вам предоставлен доступ к тарифу <b>KUKAI Pro</b> на 30 дней.\n\n"
                f"🔑 <b>Лицензионный ключ:</b>\n"
                f"<code>{key}</code>\n\n"
                "<i>Скопируйте этот ключ и вставьте его в настройки плагина KUKAI в Autodesk Revit для активации.</i>"
            )
            await bot.send_message(user_chat_id, user_text)

            # Notify founder
            await bot.send_message(
                FOUNDER_CHAT_ID,
                f"✅ <b>Лицензия выдана успешно!</b>\n"
                f"Ключ: <code>{key}</code>\n"
                f"Для пользователя: @{username} (ID: {user_chat_id})"
            )

            # Clear from pending
            PENDING_PAYMENTS.pop(payment_id, None)
            await bot.answer_callback_query(query_id, "Лицензия выпущена!")

        except Exception as e:
            logger.exception("Error generating license in Telegram bot: %s", e)
            await bot.send_message(FOUNDER_CHAT_ID, f"❌ Ошибка генерации лицензии: {e}")
            await bot.answer_callback_query(query_id, "Ошибка базы данных")

    # 2. Reject Payment
    elif action == "reject":
        await bot.send_message(
            user_chat_id,
            "❌ <b>Ваш платеж был отклонен фаундером.</b>\n"
            "Если у вас возникли вопросы, свяжитесь с поддержкой @kuklev9797.",
        )
        await bot.send_message(
            FOUNDER_CHAT_ID,
            f"❌ <b>Платеж {payment_id} отклонен.</b>\n"
            f"Пользователь @{username} уведомлен.",
        )
        PENDING_PAYMENTS.pop(payment_id, None)
        await bot.answer_callback_query(query_id, "Платеж отклонен")


# --- Periodical Cron Tasks ---

async def run_stability_report_cron(bot: TelegramBotClient, db: Database):
    """Task that runs every 12 hours to analyze logs and errors in Postgres and report to founder."""
    while True:
        # Wait 12 hours
        await asyncio.sleep(12 * 60 * 60)
        try:
            logger.info("Running stability audit cron task...")
            # Query recently logged errors in telemetry_requests
            # In KUKAI db, we can check the logs
            pool = await db._get_pool()

            # Count transactions and errors
            async with pool.acquire() as conn:
                total_reqs = await conn.fetchval(
                    "SELECT COUNT(*) FROM audit_log WHERE created_at >= to_char(now() - interval '12 hours', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')"
                )
                error_reqs = await conn.fetchval(
                    "SELECT COUNT(*) FROM audit_log WHERE result = 'error' AND created_at >= to_char(now() - interval '12 hours', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')"
                )

                # Fetch recent errors
                rows = await conn.fetch(
                    "SELECT action, details, created_at FROM audit_log WHERE result = 'error' ORDER BY created_at DESC LIMIT 5"
                )

            success_rate = 100.0 if not total_reqs else ((total_reqs - error_reqs) / total_reqs) * 100.0

            report = (
                f"📊 <b>Stability Report (за последние 12 часов):</b>\n\n"
                f"🔹 <b>Всего транзакций к ИИ:</b> {total_reqs}\n"
                f"🔹 <b>Ошибок транзакций:</b> {error_reqs}\n"
                f"🔹 <b>Уровень успеха (Success Rate):</b> {success_rate:.2f}%\n\n"
            )

            if rows:
                report += "⚠️ <b>Последние сбои Revit API / Roslyn:</b>\n"
                for r in rows:
                    details = json.loads(r["details"]) if r["details"] else {}
                    err_msg = details.get("error", "Неизвестная ошибка")[:100]
                    report += f"• <code>{r['action']}</code>: <i>{err_msg}</i>\n"
            else:
                report += "✨ Никаких сбоев или ошибок за 12 часов не зафиксировано! Идеальная стабильность."

            await bot.send_message(FOUNDER_CHAT_ID, report)

        except Exception as e:
            logger.exception("Error in stability report cron: %s", e)


async def run_churn_interview_cron(bot: TelegramBotClient, db: Database):
    """Task that runs every 24 hours to find inactive users (14+ days) and alert the founder or ping them."""
    while True:
        # Wait 24 hours
        await asyncio.sleep(24 * 60 * 60)
        try:
            logger.info("Running churn checker cron task...")
            pool = await db._get_pool()

            # Find users whose last action was more than 14 days ago
            # In KUKAI schema: devices contains last_seen, licenses contains expires_at
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT key, name, tier, expires_at FROM licenses
                    WHERE active = 1 AND tier != 'free' AND key IN (
                        SELECT license_key FROM devices
                        GROUP BY license_key
                        HAVING max(last_seen) < to_char(now() - interval '14 days', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"')
                    )
                    """
                )

            if rows:
                alert_text = "🚪 <b>Выявлены пользователи на пороге оттока (Churn Alert):</b>\n\n"
                for r in rows:
                    alert_text += f"• {r['name']} (Ключ: <code>{r['key'][:12]}...</code>)\n"
                    alert_text += f"  Тариф: <b>{r['tier']}</b>. Не активен 14+ дней.\n\n"
                alert_text += "💡 <i>ИИ-Интервьюер Churn готов отправить им мягкое напоминание и опрос при первой активности, или вы можете связаться с ними лично.</i>"
                await bot.send_message(FOUNDER_CHAT_ID, alert_text)

        except Exception as e:
            logger.exception("Error in churn interview cron: %s", e)


# --- Background Task Starter (Lifespan Integration) ---

async def start_telegram_bot(db: Database, license_manager: LicenseManager):
    """Main entry point to start the bot background tasks.

    Can be imported in main.py and spawned via asyncio.create_task().
    """
    settings = get_settings()
    # Gemini AI Studio key for OCR checks
    gemini_key = settings.llm_api_key or settings.llm_google_backup_api_key

    bot = TelegramBotClient(BOT_TOKEN)

    # Spawn background loops
    updates_task = asyncio.create_task(
        process_telegram_updates(bot, db, license_manager, gemini_key)
    )
    stability_task = asyncio.create_task(
        run_stability_report_cron(bot, db)
    )
    churn_task = asyncio.create_task(
        run_churn_interview_cron(bot, db)
    )

    try:
        await asyncio.gather(updates_task, stability_task, churn_task)
    except asyncio.CancelledError:
        logger.info("Telegram dispatcher shutting down...")
    finally:
        updates_task.cancel()
        stability_task.cancel()
        churn_task.cancel()
        await bot.close()
