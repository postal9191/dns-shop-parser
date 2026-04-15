#!/usr/bin/env python3
"""Тест Qrator resolver"""

import asyncio
from parser.qrator_resolver import resolve_qrator_cookies
from utils.logger import logger

async def test():
    logger.info("Тестирую solve_qrator.js...")
    result = await resolve_qrator_cookies()

    if result:
        logger.info(f"✅ Успех! Получена кука: {result}")
        if 'qrator_jsid2' in result:
            jsid2 = result['qrator_jsid2']
            logger.info(f"   qrator_jsid2: {jsid2[:50]}...")
    else:
        logger.error("❌ Ошибка: не удалось получить куку")

if __name__ == "__main__":
    asyncio.run(test())
