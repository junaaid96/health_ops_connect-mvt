#!/usr/bin/env bash
# Render build step: install deps, collect static files, apply migrations.
# The compiled CSS (static/css/app.css) and vendored JS are committed, so no
# Node toolchain is needed at deploy time.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Uploaded media lives on an ephemeral disk on Render: restore the bundled demo
# doctor photos on every deploy so seeded profiles keep their pictures.
python manage.py seed_demo --media

# Seed the demo hospital once (no-op for the main data if doctors already exist;
# refreshes today's demo queue so the demo always has live activity).
if [ "${SEED_DEMO:-false}" = "true" ]; then
  python manage.py seed_demo
fi
