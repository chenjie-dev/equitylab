#!/usr/bin/env bash
# 因子 IC + 回测冒烟：经网关打 research（须 compose 已起）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GW="${GATEWAY_URL:-http://127.0.0.1:3000}"
# research 在 compose 内；冒烟优先网关反代，其次直连映射（若有）
IC_URL="${FACTOR_IC_URL:-}"
BT_URL="${BACKTEST_URL:-}"

if [[ -z "$IC_URL" ]]; then
  if curl -sf "$GW/health" >/dev/null 2>&1; then
    # 网关通常剥 /api/research 前缀
    IC_URL="$GW/api/research/factors/ic"
    BT_URL="$GW/api/research/backtests/run"
  else
    IC_URL="http://127.0.0.1:8002/factors/ic"
    BT_URL="http://127.0.0.1:8002/backtests/run"
  fi
fi

echo "== POST factors/ic =="
IC_BODY=$(curl -sf -X POST "$IC_URL" \
  -H 'content-type: application/json' \
  -d '{"factor":"momentum","windowYears":3,"universe":"600519","lookback":20,"horizon":5}') \
  || { echo "factor ic request failed (is research up? cold bars for 600519?)"; exit 1; }
echo "$IC_BODY" | head -c 800
echo

echo "$IC_BODY" | grep -q '"demo": false\|"demo":false' \
  || { echo "FAIL: expected demo=false"; exit 1; }
echo "$IC_BODY" | grep -q 'postgres\|cold_ts_ic\|ts_ic' \
  || { echo "WARN: source/mode may not be cold path"; }
echo "$IC_BODY" | grep -q '"ic":' \
  || { echo "FAIL: missing ic"; exit 1; }

echo "== POST backtests/run =="
BT_BODY=$(curl -sf -X POST "$BT_URL" \
  -H 'content-type: application/json' \
  -d '{"strategy":"dual_ma","fast":20,"slow":60,"universe":"600519.SH","period":"1d","count":180,"adjust":"none"}') \
  || { echo "backtest request failed"; exit 1; }
echo "$BT_BODY" | head -c 600
echo
echo "$BT_BODY" | grep -q 'cum_return\|"metrics"' \
  || { echo "FAIL: missing backtest metrics"; exit 1; }

echo "OK smoke-factor-ic"
