#!/bin/bash


python -m playwright install chromium
playwright install --with-deps chromium
playwright install-deps