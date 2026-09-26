#!/usr/bin/env bash
# Vercel build step. Vercel installs requirements.txt and runs collectstatic
# itself (serving the files from its CDN); this script only prepares the
# database and object storage.
set -o errexit

python manage.py migrate --no-input

# Make sure the bundled demo doctor photos are in object storage.
python manage.py seed_demo --media

# Load the demo hospital (first run) or refresh today's demo queue.
if [ "${SEED_DEMO:-false}" = "true" ]; then
  python manage.py seed_demo
fi
