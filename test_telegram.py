"""
Telegram connection test — RF Scalp Bot
Run: python test_telegram.py
"""
from telegram_alert import TelegramAlert
from config_loader import load_settings

if __name__ == "__main__":
    _name = load_settings().get("bot_name", "RF Scalp")
    alert = TelegramAlert()
    ok = alert.send(
        f"✅ Test message — Telegram is connected and working!\n"
        f"{_name} is ready to deploy."
    )
    if ok:
        print("✅ Message sent successfully.")
    else:
        print("❌ Failed to send. Check TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in secrets.json.")
