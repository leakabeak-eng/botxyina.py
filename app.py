"""
FunPay бот: автоподнятие лотов, автоответ на отзывы, чаты и возвраты через Telegram.

Установка:
    pip install FunPayAPI pyTelegramBotAPI

Запуск:
    1. Заполни блок НАСТРОЙКИ ниже
    2. python funpay_bot.py

FunPayAPI - неофициальная библиотека (движок FunPay Cardinal). Если после
обновления библиотеки какие-то методы называются иначе - смотри её исходники.
"""

import re
import time
import logging
import threading

import telebot
from telebot import types
from FunPayAPI import Account, Runner, exceptions
from FunPayAPI.common.enums import EventTypes, MessageTypes

# ===================== НАСТРОЙКИ =====================
GOLDEN_KEY = "8pkzfur04rs7u67ywyrnvgbwmtfvgg0l"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "\
             "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TG_TOKEN = "8928446887:AAGCLIN0JTB9RYb4UrJcOg6Y6-lUL8Ihf4o"
ADMIN_ID = 1593210161        # твой Telegram ID (узнать у @userinfobot)

AUTO_RAISE = True             # автоподнятие лотов
AUTO_REVIEW_REPLY = True      # автоответ на отзывы
POLL_DELAY = 4                # как часто опрашивать FunPay (сек)

REVIEW_REPLIES = {            # ответ по количеству звёзд
    5: "Спасибо за отзыв и покупку! Буду рад видеть вас снова 🙌",
    4: "Спасибо за отзыв! Если что-то не устроило - напишите, поможем.",
    3: "Спасибо за отзыв. Напишите, что можно улучшить - постараюсь исправить.",
    2: "Спасибо за отзыв. Напишите мне в чат, разберёмся и решим вопрос.",
    1: "Сожалею, что так вышло. Напишите мне в чат, всё исправим.",
}
# =====================================================

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("funpay-bot")

bot = telebot.TeleBot(TG_TOKEN, parse_mode="HTML")
acc = Account(GOLDEN_KEY, USER_AGENT).get()
log.info("Вход выполнен: %s (id %s)", acc.username, acc.id)

# admin_id -> chat_id FunPay, в который админ сейчас пишет ответ
reply_state: dict[int, int] = {}


def esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def notify(text: str, markup=None):
    try:
        bot.send_message(ADMIN_ID, text, reply_markup=markup)
    except Exception as e:
        log.error("Telegram: %s", e)


# ---------------------- АВТОПОДНЯТИЕ ----------------------
def raise_loop():
    while True:
        wait_times = []
        try:
            profile = acc.get_user(acc.id)
            categories = profile.get_sorted_categories()  # {category_id: [lots]}
            for cat_id in categories:
                try:
                    acc.raise_lots(cat_id)
                    log.info("Поднята категория %s", cat_id)
                    time.sleep(1)
                except exceptions.RaiseError as e:
                    wait = getattr(e, "wait_time", None) or 3600
                    wait_times.append(wait)
                except Exception as e:
                    log.error("Ошибка поднятия %s: %s", cat_id, e)
                    wait_times.append(600)
        except Exception as e:
            log.error("Ошибка получения лотов: %s", e)
            wait_times.append(600)
        time.sleep(max(60, min(wait_times) if wait_times else 3600))


# ---------------------- ОБРАБОТКА СОБЫТИЙ FUNPAY ----------------------
def handle_review(message):
    """Пришёл отзыв - отвечаем автоматически."""
    m = re.search(r"#([A-Z0-9]{8})", message.text or "")
    if not m:
        return
    order_id = m.group(1)
    try:
        order = acc.get_order(order_id)
        stars = order.review.stars if order.review else 5
        text = order.review.text if order.review else ""
        notify(f"⭐ <b>Отзыв {stars}/5</b> по заказу #{order_id}\n{esc(text)}")
        if AUTO_REVIEW_REPLY:
            acc.send_review(order_id, REVIEW_REPLIES.get(stars, REVIEW_REPLIES[5]))
            notify(f"↩️ Автоответ на отзыв #{order_id} отправлен")
    except Exception as e:
        log.error("Отзыв %s: %s", order_id, e)
        notify(f"⚠️ Не удалось ответить на отзыв #{order_id}: {esc(str(e))}")


def funpay_loop():
    runner = Runner(acc)
    for event in runner.listen(requests_delay=POLL_DELAY):
        try:
            if event.type == EventTypes.NEW_MESSAGE:
                msg = event.message
                if msg.type in (MessageTypes.NEW_FEEDBACK, MessageTypes.FEEDBACK_CHANGED):
                    handle_review(msg)
                    continue
                if msg.author_id == acc.id:      # свои сообщения не пересылаем
                    continue
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton(
                    "✉️ Ответить", callback_data=f"reply:{msg.chat_id}"))
                notify(f"💬 <b>{esc(msg.chat_name)}</b> (chat {msg.chat_id})\n"
                       f"{esc(msg.text or '[без текста]')}", kb)

            elif event.type == EventTypes.NEW_ORDER:
                o = event.order
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton(
                    "💸 Вернуть деньги", callback_data=f"refund:{o.id}"))
                notify(f"🛒 <b>Новый заказ #{o.id}</b>\n{esc(o.description)}\n"
                       f"Сумма: {o.price} | Покупатель: {esc(o.buyer_username)}", kb)
        except Exception as e:
            log.error("Событие: %s", e)


# ---------------------- TELEGRAM ----------------------
def admin_only(func):
    def wrapper(obj, *a, **kw):
        uid = obj.from_user.id
        if uid != ADMIN_ID:
            return
        return func(obj, *a, **kw)
    return wrapper


@bot.message_handler(commands=["start", "help"])
@admin_only
def cmd_help(m):
    bot.send_message(m.chat.id,
        "<b>Команды:</b>\n"
        "/send &lt;chat_id&gt; &lt;текст&gt; - написать в чат FunPay\n"
        "/refund &lt;ORDER_ID&gt; - вернуть деньги за заказ\n"
        "/raise - поднять лоты сейчас\n"
        "/balance - баланс аккаунта\n\n"
        "Или жми кнопки под входящими сообщениями и заказами.")


@bot.message_handler(commands=["send"])
@admin_only
def cmd_send(m):
    parts = m.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        return bot.reply_to(m, "Формат: /send chat_id текст")
    try:
        acc.send_message(int(parts[1]), parts[2])
        bot.reply_to(m, "✅ Отправлено")
    except Exception as e:
        bot.reply_to(m, f"❌ {esc(str(e))}")


@bot.message_handler(commands=["refund"])
@admin_only
def cmd_refund(m):
    parts = m.text.split()
    if len(parts) != 2:
        return bot.reply_to(m, "Формат: /refund ORDER_ID")
    order_id = parts[1].lstrip("#")
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Да, вернуть", callback_data=f"refund_ok:{order_id}"),
           types.InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
    bot.reply_to(m, f"Вернуть деньги за заказ <b>#{esc(order_id)}</b>?", reply_markup=kb)


@bot.message_handler(commands=["raise"])
@admin_only
def cmd_raise(m):
    done, errors = 0, []
    for cat_id in acc.get_user(acc.id).get_sorted_categories():
        try:
            acc.raise_lots(cat_id)
            done += 1
        except exceptions.RaiseError as e:
            errors.append(f"{cat_id}: ждать {getattr(e, 'wait_time', '?')} сек")
        except Exception as e:
            errors.append(f"{cat_id}: {e}")
    bot.reply_to(m, f"Поднято категорий: {done}\n" + esc("\n".join(errors)))


@bot.message_handler(commands=["balance"])
@admin_only
def cmd_balance(m):
    acc.get()
    bot.reply_to(m, f"💰 Баланс: {acc.total_balance} ₽")


@bot.callback_query_handler(func=lambda c: True)
@admin_only
def on_button(c):
    action, _, value = c.data.partition(":")
    if action == "reply":
        reply_state[c.from_user.id] = int(value)
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
                         f"Напиши текст ответа для чата {value} (или /cancel).")
    elif action == "refund":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ Да, вернуть", callback_data=f"refund_ok:{value}"),
               types.InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
                         f"Вернуть деньги за заказ <b>#{esc(value)}</b>?", reply_markup=kb)
    elif action == "refund_ok":
        try:
            acc.refund(value)
            bot.edit_message_text(f"✅ Возврат по заказу #{esc(value)} выполнен",
                                  c.message.chat.id, c.message.message_id)
        except Exception as e:
            bot.edit_message_text(f"❌ Ошибка возврата: {esc(str(e))}",
                                  c.message.chat.id, c.message.message_id)
    elif action == "cancel":
        bot.edit_message_text("Отменено", c.message.chat.id, c.message.message_id)


@bot.message_handler(commands=["cancel"])
@admin_only
def cmd_cancel(m):
    reply_state.pop(m.from_user.id, None)
    bot.reply_to(m, "Отменено")


@bot.message_handler(func=lambda m: True, content_types=["text"])
@admin_only
def on_text(m):
    chat_id = reply_state.pop(m.from_user.id, None)
    if chat_id is None:
        return
    try:
        acc.send_message(chat_id, m.text)
        bot.reply_to(m, "✅ Отправлено")
    except Exception as e:
        bot.reply_to(m, f"❌ {esc(str(e))}")


# ---------------------- ЗАПУСК ----------------------
if __name__ == "__main__":
    if AUTO_RAISE:
        threading.Thread(target=raise_loop, daemon=True).start()
    threading.Thread(target=funpay_loop, daemon=True).start()
    notify("🤖 Бот запущен")
    bot.infinity_polling(skip_pending=True)
