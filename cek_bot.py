import asyncio
import os
from dotenv import load_dotenv
from bot import bot, dp, router

load_dotenv()

async def main():
    print("🚀 [TEST] Mencoba menjalankan bot secara mandiri...")
    print(f"Token: {os.getenv('BOT_TOKEN')[:10]}***")
    
    # Masukin router
    dp.include_router(router)
    
    # Hapus webhook lama biar gak bentrok
    await bot.delete_webhook(drop_pending_updates=True)
    
    print("✅ [TEST] Bot Telegram Standby! Coba chat /start sekarang...")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ [TEST] Error: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())