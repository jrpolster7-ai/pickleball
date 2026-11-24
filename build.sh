#!/usr/bin/env bash
# Render runs this on every deploy (see render.yaml).
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py ensure_admin
