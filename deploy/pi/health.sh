#!/usr/bin/env bash
# Healthy = backend and frontend answer on loopback (the frontend through its /api
# rewrite), both services are active and the 11 timers are loaded. Spends no
# Claude usage. Exit 0 = ok, 2 = the site works but needs attention (a failed
# job, no claude CLI: a rollback would not fix either), 1 = broken.
set -uo pipefail
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
problems=()
warnings=()

# retries cover the seconds uvicorn and next take after a restart
for url in http://127.0.0.1:8000/api/health http://127.0.0.1:3001/api/health; do
  if ! curl -fsS --retry 30 --retry-connrefused --retry-delay 1 --max-time 5 -o /dev/null "$url"; then
    problems+=("não responde: $url")
  fi
done

timers=$(systemctl --user list-timers 'investimentos-*' --all --no-legend | wc -l)
[ "$timers" -eq 11 ] || problems+=("timers investimentos-*: $timers, esperado 11")

for svc in investimentos-backend investimentos-frontend; do
  systemctl --user is-active --quiet "$svc" || problems+=("$svc não está ativo")
done
# A failed scheduled job is reported, not fatal: it may predate this deploy (a
# revoked token fails the weekly too) and each job already alerts in the app.
failed=$(systemctl --user list-units 'investimentos-*' --all --state=failed --no-legend --plain | awk '{print $1}')
[ -z "$failed" ] || warnings+=("jobs em falha: $(echo "$failed" | tr '\n' ' ')")

command -v claude >/dev/null || warnings+=("CLI claude fora do PATH: consultor e comitê param")

if [ "${#problems[@]}" -gt 0 ]; then
  printf 'investimentos: %s\n' "${problems[@]}" "${warnings[@]}" >&2
  exit 1
fi
if [ "${#warnings[@]}" -gt 0 ]; then
  printf 'investimentos: aviso: %s\n' "${warnings[@]}" >&2
  exit 2
fi
echo ok
