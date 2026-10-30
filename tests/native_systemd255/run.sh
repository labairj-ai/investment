#!/bin/bash
set -euo pipefail
# Ephemeral CI container only. Refuse the actual production layout unconditionally.
test "$(uname -s)" = Linux
test ! -d /home/optiplex/investment
test "${GITHUB_ACTIONS:-}" = true
out="${1:?diagnostic output directory required}"
mkdir -p "$out"
image="scout-v255-fixture:${GITHUB_RUN_ID:?}"
name="scout-v255-fixture-${GITHUB_RUN_ID}"
cleanup() { docker logs "$name" > "$out/container.log" 2>&1 || true; docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker build -t "$image" tests/native_systemd255 > "$out/build.log" 2>&1
docker run --detach --name "$name" --privileged --cgroupns=private --tmpfs /run --tmpfs /run/lock --tmpfs /tmp --env container=docker "$image"
for n in $(seq 1 30); do
 if docker exec "$name" systemctl show --property=Version >/dev/null 2>&1; then break; fi
 sleep 1
done
docker exec "$name" dpkg-query -W -f='${Version}' systemd > "$out/package-version.txt"
docker exec "$name" systemctl start provenance-proof.timer
complete=false
for n in $(seq 1 45); do
 count=$(docker exec "$name" sh -c 'test ! -f /var/lib/provenance-proof/records.jsonl || wc -l < /var/lib/provenance-proof/records.jsonl')
 if [[ "${count:-0}" -ge 6 ]]; then complete=true; break; fi
 sleep 1
done
docker exec "$name" journalctl -u provenance-proof.service --no-pager > "$out/fixture-journal.log"
test "$complete" = true
docker cp "$name:/var/lib/provenance-proof/records.jsonl" "$out/records.jsonl"
python tests/native_systemd255/verify.py "$out/records.jsonl" "$out/package-version.txt" > "$out/result.json"
cat "$out/result.json"
