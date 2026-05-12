# arduino-otto-mcp

FastAPI сервер для управления роботом OTTO через Bluetooth (модуль HM-10).

## Требования

- Python 3.12+
- Bluetooth-адаптер на хосте с запущенным BlueZ (`bluetoothd`)
- OTTO с прошивкой из [bluetooth_sketch.ino](bluetooth_sketch.ino)

> **macOS:** запускайте сервер напрямую, без Docker — контейнеры на macOS не имеют доступа к Bluetooth-адаптеру хоста.

## Запуск

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

При старте сервер автоматически сканирует и подключается к устройству `HMSoft`. Swagger UI доступен на [http://localhost:8000/docs](http://localhost:8000/docs).

## Запуск через Docker (Linux)

```bash
docker compose up -d --build
docker compose logs -f otto-api
```

## Подключение MCP-клиентов

Сервер реализует протокол [MCP](https://modelcontextprotocol.io) поверх REST API — LLM может управлять роботом напрямую через инструменты.

MCP-эндпоинт: `http://localhost:8000/mcp`

### Claude Desktop

Добавьте в `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "otto": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### Claude Code

```bash
claude mcp add otto http://localhost:8000/mcp
```

После подключения LLM получает три инструмента:

| Инструмент     | Описание                                      |
|----------------|-----------------------------------------------|
| `get_status`   | Проверить статус Bluetooth-соединения         |
| `send_command` | Отправить команду роботу (forward/back/…)     |
| `list_commands`| Получить список доступных команд             |

## API

### Статус соединения

```bash
curl http://localhost:8000/status
```

```json
{
  "connected": true,
  "device": "HMSoft",
  "device_address": "AA:BB:CC:DD:EE:FF"
}
```

### Список команд

```bash
curl http://localhost:8000/commands
```

```json
{
  "commands": {
    "forward": "Sends 'F'",
    "back":    "Sends 'B'",
    "left":    "Sends 'L'",
    "right":   "Sends 'R'",
    "tiptoe":  "Sends 'T'",
    "stop":    "Sends 'S'"
  }
}
```

### Отправка команды

```bash
curl -X POST http://localhost:8000/command/forward
```

```json
{"command": "forward", "sent": "F"}
```

| Команда  | Байт | Действие          |
|----------|------|-------------------|
| forward  | `F`  | Шаг вперёд        |
| back     | `B`  | Шаг назад         |
| left     | `L`  | Поворот влево     |
| right    | `R`  | Поворот вправо    |
| tiptoe   | `T`  | Качание на носках |
| stop     | `S`  | Исходная позиция  |

### Коды ошибок

| Код | Причина                                      |
|-----|----------------------------------------------|
| 503 | Сервер ещё не подключился к `HMSoft`         |
| 404 | Неизвестное имя команды                      |
