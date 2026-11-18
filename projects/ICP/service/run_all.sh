#!/usr/bin/env bash
# Regenerate every M2 table and plot (T5/T6 then T7). Does not edit the underlying scripts.
set -euo pipefail
SERVICE="$(cd "$(dirname "$0")" && pwd)"
cd "$SERVICE"

bash profile/run_profile.sh --report-only
bash run_milestone2.sh --report-only

T6="$SERVICE/results/report"
T7="${T7_WORK:-$HOME/icp/t7}/report"

echo
echo "=== M2 tables and plots ==="
echo "T5/T6 → $T6"
echo "  t5_sla.{csv,tex,png}"
echo "  t6_table.{csv,md,tex}"
echo "  t6_breakdown.{csv,tex}"
echo "  t6_acc_vs_p95.png"
echo "  t6_acc_vs_maxtput.png"
echo "T7 → $T7"
echo "  t7_pareto.{png,pdf}"
echo "  t7_configurations.{csv,md}"
