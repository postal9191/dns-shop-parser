#!/usr/bin/env node

/**
 * Собирает city_path/current_path куки и кол-во уценённых товаров
 * для всех столиц областей РФ через Playwright.
 *
 * Запуск: node scripts/collect_cities.js
 */

const { chromium } = require('playwright-extra');
const path = require('path');
const os = require('os');
const fs = require('fs');

// Список столиц областей РФ
const CITIES = [
  { name: 'Москва', slug: 'moscow' },
  { name: 'Санкт-Петербург', slug: 'spb' },
  { name: 'Новосибирск', slug: 'novosibirsk' },
  { name: 'Краснодар', slug: 'krasnodar' },
  { name: 'Екатеринбург', slug: 'ekaterinburg' },
  { name: 'Казань', slug: 'kazan' },
  { name: 'Уфа', slug: 'ufa' },
  { name: 'Нижний Новгород', slug: 'nizhny-novgorod' },
  { name: 'Челябинск', slug: 'chelyabinsk' },
  { name: 'Самара', slug: 'samara' },
  { name: 'Ростов-на-Дону', slug: 'rostov-na-donu' },
  { name: 'Омск', slug: 'omsk' },
  { name: 'Красноярск', slug: 'krasnoyarsk' },
  { name: 'Воронеж', slug: 'voronezh' },
  { name: 'Пермь', slug: 'perm' },
  { name: 'Волгоград', slug: 'volgograd' },
  { name: 'Владивосток', slug: 'vladivostok' },
  { name: 'Саратов', slug: 'sarator' },
  { name: 'Тюмень', slug: 'tyumen' },
  { name: 'Тольятти', slug: 'tolyatti' },
  { name: 'Ижевск', slug: 'izhevsk' },
  { name: 'Барнаул', slug: 'barnaul' },
  { name: 'Иркутск', slug: 'irkutsk' },
  { name: 'Хабаровск', slug: 'habarovsk' },
  { name: 'Ярославль', slug: 'yaroslavl' },
  { name: 'Владимир', slug: 'vladimir' },
  { name: 'Севастополь', slug: 'sevastopol' },
  { name: 'Ставрополь', slug: 'stavropol' },
  { name: 'Сочи', slug: 'sochi' },
  { name: 'Томск', slug: 'tomsk' },
];

const TARGET_URL = 'https://www.dns-shop.ru/catalog/markdown/';
const TIMEOUT = 50000;
const USER_DATA_DIR = path.join(os.homedir(), '.dns-collector-chromium');

const results = [];

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function collectCityData(context, page, city) {
  try {
    // Очищаем старые qrator куки
    try {
      await context.clearCookies({ name: /^qrator/ });
    } catch (e) {}

    console.error(`[${city.name}] Переход на страницу...`);
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: TIMEOUT });

    // Ждём решения Qrator challenge
    await sleep(5000);

    // Собираем только нужные cookies
    const cookies = await context.cookies();
    const cookieDict = {};
    for (const c of cookies) {
      if (c.domain && (c.domain.includes('dns-shop.ru') || c.domain.includes('dns-shop') || c.domain.startsWith('.'))) {
        // Сохраняем только нужные куки
        if (['city_path', 'current_path', 'qrator_jsid2', 'qrator_jsr', 'PHPSESSID', '_csrf'].includes(c.name)) {
          cookieDict[c.name] = c.value;
        }
      }
    }

    // Ищем city_path и current_path
    const cityPath = cookieDict['city_path'] || null;
    const currentPath = cookieDict['current_path'] || null;

    // Получаем количество товаров из title страницы
    let productCount = null;
    const title = await page.title();
    const match = title.match(/(\d+)/);
    if (match) {
      productCount = parseInt(match[1]);
    }

    // Ищем в контенте
    if (!productCount) {
      const bodyText = await page.evaluate(() => document.body.textContent);
      const countMatch = bodyText.match(/показа[но|ы]\s*(\d+)/i) ||
                         bodyText.match(/товар[ов]?\s*-\s*(\d+)/i) ||
                         bodyText.match(/(\d+)\s*предложен/i);
      if (countMatch) {
        productCount = parseInt(countMatch[1]);
      }
    }

    // Ищем в заголовке
    if (!productCount) {
      try {
        const h1 = await page.$('h1');
        if (h1) {
          const h1Text = await h1.textContent();
          const h1Match = h1Text.match(/(\d+)/);
          if (h1Match) {
            productCount = parseInt(h1Match[1]);
          }
        }
      } catch {}
    }

    // Ищем в data-role="items-count"
    if (!productCount) {
      try {
        const countEl = await page.$('[data-role="items-count"]');
        if (countEl) {
          const text = await countEl.textContent();
          const match = text.match(/(\d+)/);
          if (match) {
            productCount = parseInt(match[1]);
          }
        }
      } catch {}
    }

    // Ищем в .markdown-page__markdown-count
    if (!productCount) {
      try {
        const countEl = await page.$('.markdown-page__markdown-count');
        if (countEl) {
          const text = await countEl.textContent();
          const match = text.match(/(\d+)/);
          if (match) {
            productCount = parseInt(match[1]);
          }
        }
      } catch {}
    }

    // Получаем qrator_jsid2
    const qratorJsid2 = cookieDict['qrator_jsid2'] || null;

    console.error(`[${city.name}] city_path=${cityPath ? '✓' : '✗'}, current_path=${currentPath ? '✓' : '✗'}, товаров=${productCount || '?'}`);

    results.push({
      city_name: city.name,
      city_slug: city.slug,
      city_path: cityPath,
      current_path: currentPath,
      product_count: productCount,
      qrator_jsid2: qratorJsid2 ? qratorJsid2.substring(0, 20) + '...' : null,
    });

    return true;

  } catch (err) {
    console.error(`[${city.name}] Ошибка: ${err.message}`);
    results.push({
      city_name: city.name,
      city_slug: city.slug,
      city_path: null,
      current_path: null,
      product_count: null,
      error: err.message,
    });
    return false;
  }
}

async function selectCity(context, page, targetCity) {
  try {
    console.error(`[selectCity] Смена на ${targetCity.name}...`);

    // Кликаем на текущий город в хедере (иконка + название)
    const citySelectors = [
      '.header-location',
      '[class*="location"]',
      '[class*="city"]',
      'a[href*="city"]',
      '.header-city',
    ];

    let clicked = false;
    for (const selector of citySelectors) {
      const btn = await page.$(selector);
      if (btn) {
        await btn.click();
        console.error(`[selectCity] Кликнули: ${selector}`);
        clicked = true;
        break;
      }
    }

    if (!clicked) {
      console.error('[selectCity] Не найдена кнопка города');
      return false;
    }

    await sleep(2000);

    // Вводим город в поиск модального окна
    const inputSelectors = [
      'input[placeholder*="ол"]',
      'input[placeholder*="Найт"]',
      '.modal input',
      '[class*="modal"] input',
    ];

    let filled = false;
    for (const selector of inputSelectors) {
      const input = await page.$(selector);
      if (input) {
        await input.fill(targetCity.name);
        console.error(`[selectCity] Ввели: ${targetCity.name}`);
        filled = true;
        break;
      }
    }

    if (!filled) {
      console.error('[selectCity] Не найден input для поиска');
      return false;
    }

    await sleep(1500);

    // Кликаем на результат поиска
    // Ищем текст города или кнопку с городом
    const resultSelectors = [
      `button:has-text("${targetCity.name}")`,
      `a:has-text("${targetCity.name}")`,
      `[class*="city"]:has-text("${targetCity.name}")`,
    ];

    for (const selector of resultSelectors) {
      const result = await page.$(selector);
      if (result) {
        await result.click();
        console.error(`[selectCity] Выбран: ${targetCity.name}`);
        break;
      }
    }

    // Ждём перезагрузки страницы и решения Qrator
    await sleep(6000);

    return true;
  } catch (err) {
    console.error(`[selectCity] Ошибка: ${err.message}`);
    return false;
  }
}

async function main() {
  let context = null;
  let page = null;

  try {
    console.error('Запуск браузера...');

    const userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36';

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

    page = await context.newPage();
    console.error('Браузер запущен. Начинаю сбор данных...');

    for (let i = 0; i < CITIES.length; i++) {
      const city = CITIES[i];

      console.error(`\n=== [${i + 1}/${CITIES.length}] ${city.name} ===`);

      // Сначала собираем данные с текущим городом
      await collectCityData(context, page, city);

      // Если не последний город - меняем на следующий
      if (i < CITIES.length - 1) {
        const nextCity = CITIES[i + 1];
        await selectCity(context, page, nextCity);
      }

      // Небольшая пауза между запросами
      await sleep(500);
    }

    console.error('\n\n=== РЕЗУЛЬТАТЫ ===');
    console.log(JSON.stringify(results, null, 2));

    // Сохраняем в файл
    fs.writeFileSync('data/cities_data.json', JSON.stringify(results, null, 2));
    console.error('\nСохранено в data/cities_data.json');

    await page.close();
    await context.close();
    process.exit(0);

  } catch (err) {
    console.error(`Критическая ошибка: ${err.message}`);
    console.error(err.stack);

    if (page) {
      try { await page.close(); } catch {}
    }
    if (context) {
      try { await context.close(); } catch {}
    }

    process.exit(1);
  }
}

main();
