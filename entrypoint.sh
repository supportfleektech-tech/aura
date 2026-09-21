#!/bin/sh
# AURA OS entrypoint — plain uvicorn by default; Litestream replication +
# restore-on-boot when AURA_LITESTREAM_REPLICA is set.
set -e
if [ -n "$AURA_LITESTREAM_REPLICA" ]; then
  echo "litestream: replica $AURA_LITESTREAM_REPLICA"
  sed "s|\$AURA_LITESTREAM_REPLICA|$AURA_LITESTREAM_REPLICA|" /app/litestream.yml > /tmp/litestream.yml
  if [ ! -f /data/aura.db ]; then
    echo "litestream: restoring database from replica..."
    litestream restore -config /tmp/litestream.yml -if-replica-exists /data/aura.db || true
  fi
  exec litestream replicate -config /tmp/litestream.yml -- \
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
else
  echo "litestream: disabled (set AURA_LITESTREAM_REPLICA to enable)"
  exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
