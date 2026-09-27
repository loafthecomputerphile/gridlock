#!/usr/bin/env bash
# Download high-voltage transmission lines for GA + SC from Overpass API
set -euo pipefail

OUT="ga_sc_transmission_lines.json"

QUERY='[out:json][timeout:180];
(
  area["ISO3166-2"="US-GA"]->.ga;
  area["ISO3166-2"="US-SC"]->.sc;
  way["power"="line"](area.ga);
  way["power"="line"](area.sc);
);
out tags geom;'

curl -sS --max-time 300 \
  -A "hackathon-fetch/1.0" \
  -H "Accept: */*" \
  --data-urlencode "data=$QUERY" \
  "https://overpass-api.de/api/interpreter" \
  -o "$OUT"

echo "Saved: $(pwd)/$OUT ($(du -h "$OUT" | cut -f1))"