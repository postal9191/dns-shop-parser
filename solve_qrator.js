#!/usr/bin/env node

/**
 * Решение Qrator challenge через headless Playwright браузер.
 * Выводит qrator_jsid2 куку в формате, ожидаемом qrator_resolver.py
 *
 * UA можно переопределить через env var QRATOR_UA — нужно для синхронизации
 * с Python-сессией (иначе Qrator инвалидирует jsid2 при смене UA в HTTP).
 */

const { chromium } = require('playwright');
const path = require('path');
const os = require('os');

const TARGET_URL = 'https://www.dns-shop.ru/catalog/markdown/';
const TIMEOUT = 50000; // 50 сек (Python ждёт 60 сек)
const USER_DATA_DIR = path.join(os.homedir(), '.dns-parser-chromium');

async function resolveQrator() {
  let context = null;
  try {
    console.error('[solve_qrator] Запуск Playwright браузера...');

    // UA строго по реальной ОС — иначе Qrator палит рассинхрон
    // (Chromium всё равно шлёт свои client hints для текущей платформы).
    let userAgent;
    const platform = os.platform();

    if (platform === 'darwin') {
      userAgent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36';
    } else if (platform === 'linux') {
      userAgent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36';
    } else {
      userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36';
    }

    context = await chromium.launchPersistentContext(USER_DATA_DIR, {
      headless: true,
      userAgent,
      locale: 'ru-RU',
      timezoneId: 'Europe/Moscow',
      args: [
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage',
        '--no-first-run',
        '--no-default-browser-check',
      ],
    });

    const page = await context.newPage();

    // Логирование консоли браузера для отладки
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        console.error(`[browser] ${msg.text()}`);
      }
    });

    page.on('response', (response) => {
      if (response.status() === 401 || response.status() === 403) {
        console.error(`[solve_qrator] Ошибка ${response.status()} от ${response.url()}`);
      }
    });

    console.error(`[solve_qrator] Переходим на ${TARGET_URL}...`);

    try {
      await page.goto(TARGET_URL, {
        waitUntil: 'domcontentloaded',
        timeout: TIMEOUT,
      });
    } catch (err) {
      console.error(`[solve_qrator] Timeout или ошибка при переходе: ${err.message}`);
    }

    // Ждём появления qrator_jsid2 — polling вместо фиксированного wait
    console.error('[solve_qrator] Ждём решения Qrator challenge...');

    const MAX_ATTEMPTS = 3;
    let qratorCookie = null;

    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
      const deadline = Date.now() + 30000; // 30 сек на попытку
      while (Date.now() < deadline) {
        const cookies = await context.cookies();
        qratorCookie = cookies.find((c) => c.name === 'qrator_jsid2');
        if (qratorCookie) break;
        await page.waitForTimeout(500);
      }

      if (qratorCookie) break;

      if (attempt < MAX_ATTEMPTS - 1) {
        console.error(`[solve_qrator] Попытка ${attempt + 1}: qrator_jsid2 не получена, перезагружаем...`);
        try {
          await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: TIMEOUT });
        } catch (err) {
          console.error(`[solve_qrator] Ошибка при перезагрузке: ${err.message}`);
        }
      }
    }

    // Финальная проверка кук для лога
    const cookies = await context.cookies();
    console.error(`[solve_qrator] Всего кук: ${cookies.length}`);

    if (!qratorCookie) {
      console.error('[solve_qrator] ❌ qrator_jsid2 не найдена в куках');
      console.error('[solve_qrator] Доступные куки:', cookies.map((c) => c.name).join(', '));

      // Пытаемся найти хотя бы PHPSESSID
      const phpSessionCookie = cookies.find((c) => c.name === 'PHPSESSID');
      if (phpSessionCookie) {
        console.error('[solve_qrator] ⚠️  Получена PHPSESSID (без qrator_jsid2)');
      }

      process.exit(1);
    }

    console.error(`[solve_qrator] ✓ qrator_jsid2 получена: ${qratorCookie.value.substring(0, 20)}...`);

    // Собираем все куки dns-shop.ru (jsid2 + PHPSESSID + _csrf) — пригодятся в Python
    const cookiesDict = {};
    for (const c of cookies) {
      if (c.domain && c.domain.toLowerCase().includes('dns-shop.ru')) {
        cookiesDict[c.name] = c.value;
      }
    }
    // Гарантируем, что jsid2 точно там (даже если domain у неё иной)
    cookiesDict.qrator_jsid2 = qratorCookie.value;

    console.log('__QRATOR_COOKIES__');
    console.log(JSON.stringify(cookiesDict));
    console.log('__END_COOKIES__');

    await context.close();
    process.exit(0);

  } catch (err) {
    console.error(`[solve_qrator] ❌ Ошибка: ${err.message}`);
    console.error(err.stack);

    if (context) {
      try {
        await context.close();
      } catch (e) {
        // ignore
      }
    }

    process.exit(1);
  }
}

resolveQrator();
