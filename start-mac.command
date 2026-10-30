#!/usr/bin/env bash
# Balance of Power — запуск в macOS.
#
# Finder запускает .command двойным щелчком; этот файл просто передаёт
# управление общему скрипту запуска.

set -u
cd "$(dirname "$0")" || exit 1
exec bash ./start-linux.sh
