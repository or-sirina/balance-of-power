#!/usr/bin/env bash
# Balance of Power — запуск в Linux (и в macOS через start-mac.command).
#
# Скрипт переходит в свою папку (игру можно держать где угодно), проверяет
# Python и PyQt5, при необходимости предлагает установить PyQt5 и запускает
# игру. Ничего не ставит без вопроса.
#
# Порядок поиска PyQt5: системный Python; потом виртуальное окружение
# $HOME/.local/share/balance-of-power/venv (его создаёт этот скрипт, если pip
# отказывается ставить в системный Python — PEP 668).

set -u
# Portable "directory of this script": readlink -f is a GNU extension and is not
# on macOS, where this file is also used (start-mac.command calls it).
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
cd "$SCRIPT_DIR" || exit 1

VENV="${HOME:-.}/.local/share/balance-of-power/venv"

PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "Python 3.8 или новее не найден (поддерживается 3.8-3.14, 64 бит)."
    echo "Поставьте его: sudo apt install python3   (или dnf/pacman)"
    echo "Подробности — в USTANOVKA-RU.txt."
    exit 1
fi

# If a previous run created the venv, use its interpreter.
if ! "$PY" -c 'import PyQt5' >/dev/null 2>&1 && [ -x "$VENV/bin/python" ] \
        && "$VENV/bin/python" -c 'import PyQt5' >/dev/null 2>&1; then
    PY="$VENV/bin/python"
fi

if ! "$PY" -c 'import PyQt5' >/dev/null 2>&1; then
    echo "PyQt5 не установлен."
    if [ -d wheels ]; then
        echo "Нашёл папку wheels, ставлю оттуда (без интернета)..."
        "$PY" -m pip install --user --no-index --find-links wheels PyQt5 || true
    fi
fi

if ! "$PY" -c 'import PyQt5' >/dev/null 2>&1; then
    echo "Варианты установки (интернет нужен один раз):"
    echo
    if command -v apt >/dev/null 2>&1; then
        echo "    sudo apt install python3-pyqt5"
    elif command -v dnf >/dev/null 2>&1; then
        echo "    sudo dnf install python3-qt5"
    elif command -v pacman >/dev/null 2>&1; then
        echo "    sudo pacman -S python-pyqt5"
    fi
    echo "    $PY -m pip install --user PyQt5"
    echo "    (если pip пишет externally-managed-environment — PEP 668 — скрипт"
    echo "     сам попробует виртуальное окружение: $VENV)"
    echo "За прокси задайте HTTPS_PROXY=http://host:port перед запуском."
    echo
    if [ ! -t 0 ]; then
        echo "Нет терминала для вопроса. Запустите этот файл из терминала."
        exit 1
    fi
    printf "Поставить PyQt5 сейчас через pip? [y/N] "
    read -r answer || answer=n
    case "$answer" in
        y|Y|д|Д)
            if ! "$PY" -m pip install --user PyQt5; then
                echo
                echo "pip --user не сработал (PEP 668, нет pip или нет сети)."
                echo "Пробую виртуальное окружение: $VENV"
                if "$PY" -m venv "$VENV" && "$VENV/bin/python" -m pip install PyQt5; then
                    PY="$VENV/bin/python"
                else
                    echo "Не получилось. Поставьте python3-pyqt5 пакетом дистрибутива"
                    echo "(нужен python3-venv/python3-pip) или смотрите USTANOVKA-RU.txt, раздел 8."
                    exit 1
                fi
            fi
            ;;
        *)
            echo "Хорошо, поставьте вручную и запустите этот файл снова."
            exit 1
            ;;
    esac
    if ! "$PY" -c 'import PyQt5' >/dev/null 2>&1; then
        echo "PyQt5 всё ещё не импортируется. См. USTANOVKA-RU.txt, раздел 8."
        exit 1
    fi
fi

exec "$PY" main.py
