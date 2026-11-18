# use report-only to generate the report artifacts, plots, tables/csvs
set -euo pipefail
SERVICE="$(cd "$(dirname "$0")" && pwd)"
T7_WORK="${T7_WORK:-$HOME/icp/t7}"
T7_IMAGE="${T7_IMAGE:-icp-ocr:t7}"
if [[ -z "${T6_RESULTS:-}" ]]; then
  T6_RESULTS="$SERVICE/results"
  if [[ -f "$HOME/icp/runs/t6/index.json" ]]; then
    T6_RESULTS="$HOME/icp/runs"
  fi
fi

if [[ "${1:-}" != "--report-only" ]]; then
  if [[ $# -gt 0 ]]; then
    echo "usage: bash service/run_milestone2.sh [--report-only]" >&2
    exit 2
  fi
  T1_ARGS=()
  if [[ -n "${T1_RESULTS:-}" ]]; then
    T1_ARGS=(--test-results "$T1_RESULTS")
  fi
  python3 "$SERVICE/t7/t7.py" run --work "$T7_WORK" --t6 "$T6_RESULTS" --image "$T7_IMAGE" "${T1_ARGS[@]}"
elif [[ $# -ne 1 ]]; then
  echo "usage: bash service/run_milestone2.sh [--report-only]" >&2
  exit 2
fi

docker run --rm --user "$(id -u):$(id -g)" \
  -e MPLCONFIGDIR=/tmp/matplotlib -e PYTHONPATH=/app/icp \
  -v "$T7_WORK:/work" -v "$SERVICE/t7:/app/t7:ro" "$T7_IMAGE" \
  python /app/t7/report.py --work /work
echo "Tables and plots saved to $T7_WORK/report"
