#!/usr/bin/env node

/**
 * Решение Qrator challenge через headless Playwright браузер.
 * Выводит qrator_jsid2 куку в формате, ожидаемом qrator_resolver.py
 */

const { chromium } = require('playwright');

const TARGET_URL = 'https://www.dns-shop.ru/catalog/markdown/';
const TIMEOUT = 50000; // 50 сек (Python ждёт 60 сек)

async function resolveQrator() {
  let browser = null;
  try {
    console.error('[solve_qrator] Запуск Playwright браузера...');

    browser = await chromium.launch({
      headless: true,
      args: [
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage',
        '--no-first-run',
        '--no-default-browser-check',
      ],
    });

    // Определяем UserAgent в зависимости от ОС
    let userAgent;
    const platform = require('os').platform();

    if (platform === 'darwin') {
      // macOS
      userAgent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36';
    } else if (platform === 'linux') {
      // Linux
      userAgent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36';
    } else {
      // Windows (по умолчанию)
      userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36';
    }

    const context = await browser.newContext({
      userAgent,
      locale: 'ru-RU',
      timezoneId: 'Europe/Moscow',
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
        waitUntil: 'networkidle',
        timeout: TIMEOUT,
      });
    } catch (err) {
      console.error(`[solve_qrator] Timeout или ошибка при переходе: ${err.message}`);
      // Продолжаем - браузер мог получить куку даже если страница не полностью загрузилась
    }

    // Даём браузеру время на решение Qrator challenge
    console.error('[solve_qrator] Ждём решения Qrator challenge...');
    await page.waitForTimeout(2000);

    // Получаем все куки
    const cookies = await context.cookies();
    console.error(`[solve_qrator] Всего кук: ${cookies.length}`);

    const qratorCookie = cookies.find((c) => c.name === 'qrator_jsid2');

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

    // Выводим в формате, ожидаемом Python (qrator_resolver.py)
    const cookiesDict = {
      qrator_jsid2: qratorCookie.value,
    };

    console.log('__QRATOR_COOKIES__');
    console.log(JSON.stringify(cookiesDict));
    console.log('__END_COOKIES__');

    await context.close();
    await browser.close();
    process.exit(0);

  } catch (err) {
    console.error(`[solve_qrator] ❌ Ошибка: ${err.message}`);
    console.error(err.stack);

    if (browser) {
      try {
        await browser.close();
      } catch (e) {
        // ignore
      }
    }

    process.exit(1);
  }
}

resolveQrator();
