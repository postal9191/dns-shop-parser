#!/usr/bin/env node

/**
 * Решение Qrator challenge через headless Playwright браузер.
 * Выводит qrator_jsid2 куку в формате, ожидаемом qrator_resolver.py
 *
 * UA можно переопределить через env var QRATOR_UA — нужно для синхронизации
 * с Python-сессией (иначе Qrator инвалидирует jsid2 при смене UA в HTTP).
 */

// playwright-extra как фреймворк — без stealth плагина.
// stealth патчит canvas/WebGL таким образом, что Qrator видит
// несоответствие fingerprint и отдаёт 403 на /__qrator/validate.
// Чистый headless Chromium 147 проходит Qrator challenge без плагинов.
const { chromium } = require('playwright-extra');

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

    // Очищаем старые qrator куки из контекста перед навигацией.
    // Если в профиле протухшие/мусорные qrator куки — Qrator видит jsid2,
    // пропускает full challenge и не выдаёт новый валидный jsid2.
    // Чистый старт гарантирует полный challenge → свежий jsid2.
    try {
      await context.clearCookies({ name: /^qrator/ });
      console.error('[solve_qrator] Старые qrator куки очищены (принудительный fresh challenge)');
    } catch (e) {
      console.error('[solve_qrator] clearCookies недоступен, продолжаем:', e.message);
    }

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

    // Логируем все HTTP ответы для отладки
    const responses = [];
    // Флаги, которые видит основной цикл: Qrator отклонил решение challenge
    // (validate → 403 или редирект на /qrerror/403.html). Это явный сигнал
    // headless detection — дальше ждать jsid2 нет смысла.
    let validateRejected = false;
    page.on('response', (response) => {
      responses.push({
        status: response.status(),
        url: response.url(),
        time: new Date().toISOString(),
      });
      const status_emoji = {200: '✅', 401: '⚠️', 403: '⚠️'}[response.status()] || '❓';
      console.error(`[solve_qrator] HTTP ${status_emoji} ${response.status()} ${response.url()}`);

      const url = response.url();
      if (response.status() === 403 &&
          (url.includes('/__qrator/validate') || url.includes('/qrerror/403'))) {
        validateRejected = true;
      }
    });

    try {
      await page.goto(TARGET_URL, {
        waitUntil: 'domcontentloaded',
        timeout: TIMEOUT,
      });
    } catch (err) {
      console.error(`[solve_qrator] Timeout или ошибка при переходе: ${err.message}`);
    }

    // Ждём появления главной qrator куки (остальные придут тогда же) — polling
    console.error('[solve_qrator] Начинаю polling куки...');

    const MAX_ATTEMPTS = 3;
    let qratorCookie = null;
    const pollStartTime = Date.now();

    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
      const attemptStartTime = Date.now();
      const deadline = attemptStartTime + 60000; // 60 сек на попытку (Qrator может быть медленным)
      let checkCount = 0;
      while (Date.now() < deadline) {
        const cookies = await context.cookies();
        const allCookies = cookies.map((c) => c.name);

        qratorCookie = cookies.find((c) => c.name === 'qrator_jsid2' && c.value.startsWith('v2.'));
        checkCount++;

        // Логируем статус каждые 10 проверок или когда нашли jsid2
        if (checkCount % 10 === 0 || qratorCookie) {
          const elapsed = Math.floor((Date.now() - attemptStartTime) / 1000);
          console.error(`[solve_qrator] Проверка #${checkCount} (${elapsed}s): ${allCookies.length} кук, qrator_jsid2=${qratorCookie ? '✅' : '❌'}`);
          if (qratorCookie) {
            console.error(`[solve_qrator] Доступные qrator куки: ${allCookies.filter((n) => n.includes('qrator')).join(', ')}`);
          }
        }

        if (qratorCookie) break;

        // Qrator отклонил решение challenge — дальше jsid2 не появится.
        // Выходим рано, чтобы не сжигать 180 сек впустую.
        if (validateRejected) {
          console.error('[solve_qrator] ❌ Challenge отклонён (validate 403 / qrerror/403). Headless detection — нужен stealth.');
          process.exit(2);
        }

        await page.waitForTimeout(300);
      }

      if (qratorCookie) break;
      if (validateRejected) break;

      if (attempt < MAX_ATTEMPTS - 1) {
        console.error(`[solve_qrator] Попытка ${attempt + 1}: qrator_jsid2 не получена за 60s, перезагружаем...`);
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
      process.exit(1);
    }

    const elapsed_total = Math.floor((Date.now() - pollStartTime) / 1000);
    console.error(`[solve_qrator] ✓ qrator_jsid2 получена за ${elapsed_total}s`);

    // Собираем все куки dns-shop.ru (3 qrator куки + PHPSESSID + _csrf и т.д.)
    const cookiesDict = {};
    const qratorCookies = [];
    for (const c of cookies) {
      if (c.domain && c.domain.toLowerCase().includes('dns-shop.ru')) {
        cookiesDict[c.name] = c.value;
        if (c.name.includes('qrator')) {
          qratorCookies.push(c.name);
        }
      }
    }
    // Гарантируем, что jsid2 точно там (даже если domain у неё иной)
    const jsid2Cookie = cookies.find((c) => c.name === 'qrator_jsid2');
    if (jsid2Cookie) {
      cookiesDict.qrator_jsid2 = jsid2Cookie.value;
    }

    console.error(`[solve_qrator] Финально собрано кук: ${Object.keys(cookiesDict).length}`);
    console.error(`[solve_qrator] Qrator куки (${qratorCookies.length}): ${qratorCookies.join(', ')}`);
    console.error(`[solve_qrator] Все куки: ${Object.keys(cookiesDict).join(', ')}`);

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
