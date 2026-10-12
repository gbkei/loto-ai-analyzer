"""Read the draw CSVs used by Mizuho Bank's official results pages."""
import csv
import datetime as dt
import io
import json
import pathlib
import re
import unicodedata
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = 'https://www.mizuhobank.co.jp/retail/takarakuji/loto/'
GAMES = {'loto6': (2, 6, 43), 'loto7': (3, 7, 37)}


def read_csv(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'LotoResultsReader/1.1'})
    with urllib.request.urlopen(request, timeout=25) as response:
        text = response.read().decode('cp932')
    return list(csv.reader(io.StringIO(unicodedata.normalize('NFKC', text))))


def parse_date(value):
    match = re.fullmatch(r'(令和|平成|昭和)(元|\d+)年(\d+)月(\d+)日', value.strip())
    if not match:
        raise ValueError('Unrecognized official draw date: ' + value)
    era, year, month, day = match.groups()
    year = (1 if year == '元' else int(year)) + {'令和': 2018, '平成': 1988, '昭和': 1925}[era]
    date = dt.date(year, int(month), int(day))
    if date > dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date():
        raise ValueError('Future draw date')
    return date.isoformat()


def parse_header(row, game):
    match = re.fullmatch(r'第(\d+)回ロト' + game[-1], row[0].strip()) if row else None
    if not match or len(row) < 3 or int(match[1]) < 1:
        raise ValueError('Unrecognized official draw header')
    return int(match[1]), parse_date(row[2])


def parse_draw(rows, game, expected_round, expected_date):
    prefix, count, maximum = GAMES[game]
    if len(rows) < 4 or rows[0] != [f'A5{prefix}']:
        raise ValueError('Unrecognized official CSV format')
    round_number, date = parse_header(rows[1], game)
    if (round_number, date) != (expected_round, expected_date):
        raise ValueError('Official index and draw CSV disagree')
    numbers = rows[3]
    if len(numbers) <= count + 1 or numbers[0] != '本数字' or numbers[count + 1] != 'ボーナス数字':
        raise ValueError('Main number columns changed')
    values = [int(value) for value in numbers[1:count + 1]]
    if len(set(values)) != count or not all(1 <= value <= maximum for value in values):
        raise ValueError('Invalid main numbers')
    return {'round': round_number, 'date': date, 'nums': sorted(values)}


def fetch(game, previous):
    prefix, _, _ = GAMES[game]
    base = BASE + game + '/csv/'
    index_url = base + game + '.csv'
    rows = read_csv(index_url)
    draws = {row['round']: row for row in previous.get('draws', [])} if previous.get('source') == index_url else {}
    issues = []
    for i in range(0, len(rows), 2):
        if rows[i] != [f'A5{prefix}'] or i + 1 >= len(rows):
            raise ValueError('Official index format changed')
        issues.append(parse_header(rows[i + 1], game))
    if not issues or len({r for r, _ in issues}) != len(issues):
        raise ValueError('Empty or duplicate official draw index')
    issues.sort(reverse=True)
    if draws and max(draws) > issues[0][0]:
        raise ValueError('Official index regressed; keeping previous file')
    for number, date in issues[:100]:
        # Always recheck the latest draw. Existing official historical data is retained.
        if number in draws and number != issues[0][0]:
            continue
        url = base + f'A10{prefix}{number:04d}.CSV'
        draws[number] = parse_draw(read_csv(url), game, number, date)
    print(game, 'official draws', len(draws), 'latest', issues[0][0], flush=True)
    return {'source': index_url, 'draws': sorted(draws.values(), key=lambda row: row['round'], reverse=True)}


def main():
    dest = ROOT / 'data/latest.json'
    previous = json.loads(dest.read_text()) if dest.exists() else {}
    # Publish only after both games succeed; failures retain the previous file.
    games = {game: fetch(game, previous.get('games', {}).get(game, {})) for game in GAMES}
    payload = {'generatedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'games': games}
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    temp.replace(dest)


if __name__ == '__main__':
    main()
