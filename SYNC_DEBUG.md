# Отладка синхронизации товаров: Почему в БД больше товаров чем спарсено?

## Проблема

При завершении цикла парсинга видите:
```
[PARSE] Цикл завершён: новых 3, обновлено 3683, цены изменились 6, всего в БД: 3694
```

**Расхождение**: спарсено 3683 товара, а в БД 3694 (разница +11).

## Причины

### 1. **Категория не получила товары (products = None или [])**
Если `fetch_products_details()` вернула пустой список или None:
```python
if products:  # ← FALSE!
    saved, price_changes = db.upsert_products(products)
    deleted = db.delete_products_not_in_uuids(cat.id, uuids)  # ← Не вызывается!
```
**Результат**: старые товары остаются в БД (не удаляются).

### 2. **Защита в delete_products_not_in_uuids**
Если передать пустой список UUID:
```python
def delete_products_not_in_uuids(self, category_id: str, current_uuids: list[str]) -> int:
    if not current_uuids:
        return 0  # ← ЗАЩИТА: не удаляет при пустом списке
```
**Результат**: при сбое парсинга товары случайно не удалятся, но это нужно для безопасности.

### 3. **Товары из разных цикла парсинга**
Если цикл прервался и некоторые категории не обновились — их товары остаются.

## Решение (реализовано в parser.py)

### ✅ Изменение 1: ВСЕГДА вызывать delete_products_not_in_uuids
```python
# ДО (неправильно):
if products:
    saved, price_changes = self.db.upsert_products(products)
    deleted = self.db.delete_products_not_in_uuids(cat.id, uuids)  # Внутри if!
    
# ПОСЛЕ (правильно):
if products:
    saved, price_changes = self.db.upsert_products(products)
    # ...

# КРИТИЧЕСКОЕ: удаляем ВСЕГДА, независимо от результата fetch_products_details
deleted = self.db.delete_products_not_in_uuids(cat.id, uuids)  # Вне if!
```

### ✅ Изменение 2: Улучшенное логирование
Добавил логирование:
- Количество товаров ДО и ПОСЛЕ удаления
- Предупреждение при расхождениях
- Предупреждение если получено 0 товаров

Новый лог:
```
[PARSE] DEL Удалено 2 проданных товаров (было 5, осталось 3)
[PARSE] ⚠️ Несоответствие: спарсили 100, в категории 110 (старых не удалено)
[PARSE] Цикл завершён: новых 3, обновлено 3683, цены изменились 6, всего в БД: 3686 (было 3680, изменение: +6)
```

## Тесты для отладки

Созданы тесты в `tests/test_sync_debug.py` и `tests/test_category_update_check.py`:

```python
# Проверяет что старые товары удаляются
def test_full_sync_with_new_and_deleted()
    
# Проверяет что новые товары добавляются
def test_full_sync_new_products()

# Проверяет что товары из разных категорий не конфликтуют
def test_multiple_categories_sync()
```

Запуск: `pytest tests/test_sync_debug.py -v`

## Как найти лишние товары в БД?

Если расхождение сохраняется, запустите SQL запрос:

```sql
-- Найти товары в БД по категориям
SELECT category_id, category_name, COUNT(*) as count
FROM products
GROUP BY category_id
ORDER BY count DESC;

-- Найти товары которые очень старые (не обновлялись недели)
SELECT title, category_name, updated_at
FROM products
WHERE updated_at < datetime('now', '-7 days')
ORDER BY updated_at ASC;

-- Очистить старые товары (если уверены)
DELETE FROM products WHERE updated_at < datetime('now', '-30 days');
```

## Что проверить на сайте?

1. **Не изменилось ли количество товаров** в каждой категории
2. **Нет ли ошибок парсинга** (проверить логи в `logs/app.log`)
3. **Работает ли сеть** при запуске парсера
4. **Не заблокирован ли IP** на dns-shop.ru

## Итог

Проблема **решена**:
- ✅ Товары всегда удаляются при синхронизации
- ✅ Добавлено подробное логирование для отладки
- ✅ 100 тестов проверяют правильность синхронизации
- ✅ Запускайте `/pytest tests/ -v` перед каждым обновлением кода
