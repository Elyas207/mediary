TOKEN=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p')
until curl -sS -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/Elyas207/mediary/actions/runs/32579760371/jobs?per_page=20" > j.json && \
      .venv/Scripts/python.exe -c "
import json,sys
jobs=json.load(open('j.json')).get('jobs',[])
sys.exit(0 if (len(jobs)>=7 and all(j['status']=='completed' for j in jobs)) else 1)"; do
  sleep 40
done
.venv/Scripts/python.exe -c "
import json
for j in json.load(open('j.json'))['jobs']:
    print(f\"{j['name']:28} {str(j['conclusion'])}\")"
rm -f j.json
