"""Combine Rakuten's published results with thekyo's downloadable history CSVs."""
import csv
import datetime as dt
import io
import json
import pathlib
import re
import urllib.request
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parents[1]
GAMES = {'loto6': (6, 43), 'loto7': (7, 37)}


def read(url, encoding):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode(encoding)


def draw(game, number, date, values):
    count, maximum = GAMES[game]
    date = dt.date.fromisoformat(date)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    values = list(values)
    if not isinstance(number, int) or number < 1 or date > today:
        raise ValueError(f'{game}: invalid round or date')
    if len(values) != count or len(set(values)) != count or any(not isinstance(n, int) or not 1 <= n <= maximum for n in values):
        raise ValueError(f'{game}: invalid main numbers')
    return {'round': number, 'date': date.isoformat(), 'nums': sorted(values)}


def parse_rakuten(text, game):
    soup = BeautifulSoup(text, 'html.parser')
    results = {}
    for table in soup.select('table.tblNumberGuid'):
        fields = {}
        for row in table.select('tr'):
            cells = row.find_all(['th', 'td'], recursive=False)
            if cells:
                fields[cells[0].get_text(strip=True)] = [c.get_text(strip=True) for c in cells[1:]]
        if '回号' not in fields:
            continue
        m = re.fullmatch(r'第(\d+)回', ''.join(fields['回号']))
        if not m or '抽せん日' not in fields or '本数字' not in fields:
            raise ValueError(f'{game}: Rakuten table format changed')
        date = dt.datetime.strptime(''.join(fields['抽せん日']), '%Y/%m/%d').date().isoformat()
        result = draw(game, int(m[1]), date, [int(x) for x in fields['本数字']])
        if result['round'] in results:
            raise ValueError('Duplicate Rakuten round')
        results[result['round']] = result
    if not results:
        raise ValueError(f'{game}: no Rakuten results')
    return results


def parse_history(text, game):
    count, _ = GAMES[game]
    rows = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    required = ['開催回', '日付'] + [f'第{i}数字' for i in range(1, count + 1)]
    if not rows.fieldnames or not all(name in rows.fieldnames for name in required):
        raise ValueError(f'{game}: history CSV columns changed')
    results = {}
    for row in rows:
        date = dt.datetime.strptime(row['日付'], '%Y/%m/%d').date().isoformat()
        result = draw(game, int(row['開催回']), date, [int(row[f'第{i}数字']) for i in range(1, count + 1)])
        if result['round'] in results:
            raise ValueError('Duplicate history round')
        results[result['round']] = result
    if not results or sorted(results) != list(range(1, max(results) + 1)):
        raise ValueError(f'{game}: empty or incomplete history')
    return results


def fetch(game, previous):
    latest_url = f'https://takarakuji.rakuten.co.jp/backnumber/{game}/'
    history_url = f'https://{game}.thekyo.jp/data/{game}.csv'
    latest = parse_rakuten(read(latest_url, 'utf-8'), game)
    history = parse_history(read(history_url, 'cp932'), game)
    for number in latest.keys() & history.keys():
        if latest[number] != history[number]:
            raise ValueError(f'{game}: Rakuten and history disagree at round {number}')
    newest = max(latest)
    old = {r['round']: draw(game, r['round'], r['date'], r['nums']) for r in previous.get('draws', [])}
    if max(history) > newest or (old and max(old) > newest):
        raise ValueError(f'{game}: latest source is behind history; keeping previous data')
    merged = {**old, **history, **latest}
    if sorted(merged) != list(range(1, newest + 1)):
        raise ValueError(f'{game}: missing rounds')
    print(game, 'draws', len(merged), 'latest', newest, latest[newest], flush=True)
    return {
        'source': latest_url, 'sourceName': '楽天×宝くじ',
        'historySource': history_url, 'historySourceName': 'thekyo（非公式CSV）',
        'draws': sorted(merged.values(), key=lambda row: row['round'], reverse=True),
    }


def main():
    dest = ROOT / 'data/latest.json'
    previous = json.loads(dest.read_text()) if dest.exists() else {}
    # Both games must succeed before any published data is replaced.
    games = {game: fetch(game, previous.get('games', {}).get(game, {})) for game in GAMES}
    payload = {'generatedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'games': games}
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    temp.replace(dest)


if __name__ == '__main__':
    main()
