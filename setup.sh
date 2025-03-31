#!/bin/bash

# 安裝 Playwright 瀏覽器
python -m playwright install chromium
playwright install --with-deps chromium
playwright install-deps