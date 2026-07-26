# Сборка установщика Рятувальничка

## Разовая подготовка машины сборки

1. Python-окружение проекта: `.venv` с `pip install -r requirements.txt` (см. корень репо).
2. Inno Setup 6: `winget install JRSoftware.InnoSetup` (или https://jrsoftware.org/isdl.php).

## Сборка

```powershell
installer\build.ps1
```

Делает всё сразу: PyInstaller (Python + все зависимости + ffmpeg в один бандл `dist\Ryatuvalnychok\`)
→ Inno Setup (`installer\Output\RyatuvalnychokSetup.exe`). Версия берётся из `app/version.py`.

`installer\build.ps1 -SkipInstaller` — только PyInstaller-бандл, без Inno Setup (для быстрой
проверки, что сборка Python-части вообще не падает).

Модель распознавания речи (Whisper) в установщик НЕ входит — она качается при первом запуске
программы (мастер настройки, шаг «Модель розпізнавання мовлення») или лениво при первой
транскрипции. Это осознанно: устанавливать несколько сотен МБ, которые нужны не всем и не сразу,
не стоит.

## Выпуск новой версии (чтобы заработала кнопка «Перевірити оновлення»)

Механизм обновлений (`app/update_checker.py`) сверяется с `version.json`, который должен лежать
в GitHub Releases. Разовая настройка:

1. Создать GitHub-репозиторий (публичный или приватный — не важно для скачивания через
   `releases/latest/download/...`, но приватный потребует токен, публичный — нет).
2. В `app/update_checker.py` заменить `UPDATE_MANIFEST_URL`:
   `https://github.com/OWNER/REPO/releases/latest/download/version.json`
   на реальные `OWNER/REPO`.
3. Пересобрать (`installer\build.ps1`) — плейсхолдер зашит в бандл на этапе сборки.

На каждый релиз:

1. Поднять версию в `app/version.py`.
2. `installer\build.ps1` → получить `installer\Output\RyatuvalnychokSetup.exe`.
3. Создать `version.json`:
   ```json
   {
     "version": "1.1.0",
     "url": "https://github.com/OWNER/REPO/releases/download/v1.1.0/RyatuvalnychokSetup.exe",
     "notes": "Что изменилось"
   }
   ```
4. Создать GitHub Release с тегом `v1.1.0`, приложить **оба** файла как assets:
   `RyatuvalnychokSetup.exe` и `version.json`.

Дальше у всех, кто нажмёт «Перевірити оновлення», программа сама скачает новый установщик и
тихо переустановится (`/SILENT /FORCECLOSEAPPLICATIONS`) — данные пользователя не трогаются,
они не в `{app}`, а в `%LOCALAPPDATA%\Ryatuvalnychok`.

## Ручная установка поверх

Тот же `RyatuvalnychokSetup.exe`, запущенный вручную (двойной клик), сам обнаруживает
существующую установку по `AppId` в `ryatuvalnychok.iss` и обновляет её на месте — отдельного
режима не нужно.

## Тестирование на чистой машине

Через Windows Sandbox (Windows 10/11 Pro, если фича включена: `Панель управления → Программы →
Включение или отключение компонентов Windows → Изолированная среда Windows`):

1. Запустить Windows Sandbox.
2. Перетащить `installer\Output\RyatuvalnychokSetup.exe` в окно песочницы.
3. Установить, пройти мастер настройки, убедиться, что видео/аудио функции (ffmpeg,
   транскрипция) работают без предустановленного Python.
