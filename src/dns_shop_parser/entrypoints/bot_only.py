import asyncio
from dns_shop_parser.config import config
from dns_shop_parser.parser.db_manager import DBManager
from dns_shop_parser.services.telegram_bot import init_telegram_bot


async def main():
    db = DBManager(config.db_path)
    bot = init_telegram_bot(db, parser_controller=None)
    try:
        await bot.polling_loop()
    except KeyboardInterrupt:
        pass
    finally:
        await bot.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
