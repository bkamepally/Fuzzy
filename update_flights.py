"""Read public FlightStats pages; publish facts only, never execute page scripts."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

FLIGHTS = [('F9', '3283'), ('UA', '1194'), ('F9', '1085')]
BASE = 'https://www.flightstats.com/v2'


def get(url):
    request = Request(url, headers={'User-Agent': 'FuzzyFlightBoard/1.0 (personal flight status dashboard)', 'Accept': 'text/html,application/json'})
    with urlopen(request, timeout=30) as response:
        return response.read(2_000_000).decode('utf-8')


def parse_page(html):
    match = re.search(r'__NEXT_DATA__\s*=\s*', html)
    if not match:
        raise ValueError('Public page data unavailable')
    data, _ = json.JSONDecoder().raw_decode(html[match.end():])
    return data['props']['initialState']['flightTracker']


def normalize(flight, carrier, number, date, source, now):
    header = flight['resultHeader']
    if header['carrier']['fs'] != carrier or str(header['flightNumber']) != number:
        raise ValueError('Flight identity mismatch')
    if flight['schedule']['scheduledDeparture'][:10] != date:
        raise ValueError('Flight date mismatch')
    def airport(key):
        a = flight[key]
        return {k: a.get(k) for k in ('iata', 'city', 'name', 'gate', 'terminal', 'baggage', 'times', 'date')}
    status = flight['status']
    return {'id': flight['flightId'], 'departure': airport('departureAirport'),
            'arrival': airport('arrivalAirport'), 'status': status.get('status'),
            'description': status.get('statusDescription'), 'delay': status.get('delay'),
            'sourceAge': status.get('lastUpdatedText'), 'aircraft': flight.get('additionalFlightInfo', {}).get('equipment', {}).get('name'),
            'duration': flight.get('additionalFlightInfo', {}).get('flightDuration'),
            'checkedAt': now, 'source': source}


def collect(carrier, number, date, now):
    year, month, day = date.split('-')
    url = f'{BASE}/flight-tracker/{carrier}/{number}?year={year}&month={int(month)}&date={int(day)}'
    tracker = parse_page(get(url))
    records = []
    primary = tracker.get('flight')
    if primary and primary.get('schedule', {}).get('scheduledDeparture', '')[:10] == date:
        records.append(normalize(primary, carrier, number, date, url, now))
    # Some flight numbers operate more than one route on the same day.
    for group in tracker.get('otherDays', []):
        for other in group.get('flights', []):
            path = other.get('url', '')
            parsed = urlparse(path)
            query = parse_qs(parsed.query)
            if parsed.netloc or parsed.path != f'/flight-tracker/{carrier}/{number}':
                continue
            if (query.get('year', [''])[0], query.get('month', [''])[0], query.get('date', [''])[0]) != (year, str(int(month)), str(int(day))):
                continue
            if query.get('flightId', [''])[0] in [str(r['id']) for r in records]:
                continue
            extra_url = BASE + path
            extra = parse_page(get(extra_url)).get('flight')
            records.append(normalize(extra, carrier, number, date, extra_url, now))
    if not records:
        raise ValueError('No verified flight for requested date')
    return {'number': f'{carrier} {number}', 'date': date, 'segments': records, 'error': None}


def main():
    now = datetime.now(timezone.utc).isoformat()
    date = datetime.now(ZoneInfo('America/Chicago')).date().isoformat()
    old = {}
    try:
        previous = json.loads(get('https://bkamepally.github.io/Fuzzy/data.json'))
        old = {f['number']: f for f in previous.get('flights', [])}
    except Exception:
        pass
    flights = []
    for carrier, number in FLIGHTS:
        label = f'{carrier} {number}'
        try:
            record = collect(carrier, number, date, now)
        except Exception as error:
            print(f'{label}: refresh unavailable ({type(error).__name__})')
            record = old.get(label, {'number': label, 'date': date, 'segments': []}).copy()
            record['error'] = 'Latest update unavailable. Showing last verified details where available.'
        flights.append(record)
    output = {'generatedAt': now, 'requestedDate': date, 'source': 'FlightStats public flight pages', 'flights': flights}
    Path('site').mkdir(exist_ok=True)
    Path('site/index.html').write_text(Path('index.html').read_text())
    Path('site/data.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps({'date': date, 'flights': [{'number': f['number'], 'segments': len(f['segments']), 'error': f['error']} for f in flights]}))


if __name__ == '__main__':
    main()
