"""Short Chrome smoke for the full synthetic Beta 1 database; optional Playwright."""
import argparse
from datetime import date
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse


def main():
    from playwright.sync_api import sync_playwright
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--accounts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--readme-shots', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    accounts = [line.split('\t') for line in args.accounts.read_text().splitlines()[1:]]
    checks, failures, errors = [], [], []
    def check(condition, label):
        checks.append(label)
        if not condition:
            failures.append(label)
    base = args.url.rstrip('/')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel='chrome', args=['--no-sandbox'])
        context = browser.new_context(viewport={'width':1440, 'height':1000})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        def visit(path):
            response = page.goto(base + path)
            check(response.status == 200, 'HTTP ' + path)
        def count(number):
            check(page.locator('#competition-total').get_attribute('data-total') == str(number), f'count {number}')
        def overflow(label):
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), 'width ' + label)
        def labels(label):
            check(not re.search(r'\b(?:демо|demo|тест|test)\b|этап \d+',
                                page.locator('main').inner_text().casefold()), 'natural labels ' + label)
        for width in (1440,390):
            page.set_viewport_size({'width':width,'height':1000})
            visit('/competitions/');count(30)
            check(page.locator('.competition-table tbody tr').count() == 20, 'future page size')
            for mode, number in (('future',30),('past',150),('calendar',180)):
                name = dict(future='Будущие',past='Прошедшие',calendar='Календарь')[mode]
                page.get_by_role('navigation', name='Режим соревнований').get_by_role('link', name=name, exact=True).click()
                count(number);overflow(f'{width} {mode}');labels(mode)
                check(page.locator('.competition-switch [aria-current=page]').inner_text() == name, 'active ' + mode)
                dimensions = page.locator('.competition-switch a').evaluate_all('(links)=>links.map(a=>({h:a.offsetHeight,y:a.offsetTop,w:a.scrollWidth,c:a.clientWidth}))')
                check(len({d['h'] for d in dimensions}) == 1 and len({d['y'] for d in dimensions}) == 1 and
                      all(d['w'] <= d['c'] for d in dimensions), f'three equal buttons {width}')
                page.screenshot(path=str(args.output/f'{mode}-{width}.png'), full_page=True)
            for path in ('/competitions/future/151','/competitions/past/1','/'):
                visit(path);overflow(f'{width} {path}');labels(path)
            check(page.locator('.public-nav a[href="/competitions/"]').count() == 1, 'one header competition link')
            if width == 390 and args.readme_shots:
                page.screenshot(path=str(args.readme_shots/'beta1-mobile.png'), full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        visit('/competitions/?view=past')
        page.get_by_role('link',name='Далее →',exact=True).click()
        check(parse_qs(urlparse(page.url).query).get('page') == ['2'], 'past pagination page 2')
        check(page.locator('.competition-table tbody tr').count() == 20, 'past remains bounded')
        page.locator('#q').fill('ОСЕННИЙ КУБОК');page.locator('#date').fill('2024-10-16')
        page.locator('#location').fill('СЕВЕР');page.locator('#sort').select_option('name')
        page.get_by_role('button',name='Найти',exact=True).click();count(1)
        check(parse_qs(urlparse(page.url).query).get('view') == ['past'], 'filter preserves past')
        export = page.get_by_role('link',name='↓ Экспорт CSV').get_attribute('href')
        response = context.request.get(base + export)
        check(response.status == 200 and 'Осенний кубок' in response.text() and len(response.text().splitlines()) == 2, 'filtered CSV')
        page.get_by_role('link',name='Сбросить',exact=True).click();count(150)
        page.get_by_role('link',name='Календарь',exact=True).first.click()
        page.locator('#calendar-month').fill('2026-10');page.get_by_role('button',name='Перейти',exact=True).click()
        check(page.locator('.race-event.is-completed').count()>0 and page.locator('.race-event.is-planned').count()>0, 'mixed status month')
        page.get_by_role('link',name='Предыдущий месяц',exact=True).click()
        check('Сентябрь 2026' in page.locator('#calendar-heading').inner_text(),'previous month')
        page.get_by_role('link',name='Следующий месяц',exact=True).click()
        check('Октябрь 2026' in page.locator('#calendar-heading').inner_text(),'next month')
        page.locator('#calendar-month').fill('2025-10');page.get_by_role('button',name='Перейти',exact=True).click()
        check('Октябрь 2025' in page.locator('#calendar-heading').inner_text(),'change year')
        visit('/competitions/?view=calendar&month=2026-10')
        for day,kind,identifier in (('23.10.2026','future',151),('15.10.2026','past',150)):
            page.locator(f'.race-day-number[aria-label^="{day}"]').click()
            check(day in page.locator('#day-events h2').inner_text(), 'selected day ' + day)
            page.locator(f'#day-events a[href^="/competitions/{kind}/{identifier}"]').click()
            check(f'/competitions/{kind}/{identifier}' in page.url, 'day card ' + kind)
            page.get_by_role('link',name='← Календарь соревнований',exact=True).click()
            check('month=2026-10' in page.url, 'calendar month preserved ' + kind)
        # Walk only the generated months through the same browser HTTP session.
        # Each response contains a single month's records, not the full 180 rows.
        first = date(2024,10,1)
        calendar_ids = set()
        for offset in range(29):
            year = first.year + (first.month - 1 + offset)//12
            month = (first.month - 1 + offset)%12 + 1
            response = context.request.get(f'{base}/competitions/?view=calendar&month={year:04d}-{month:02d}')
            check(response.status == 200, f'calendar month {year}-{month}')
            calendar_ids.update(map(int,re.findall(r'data-competition-id="(\d+)"', response.text())))
        check(calendar_ids == set(range(1,181)), 'calendar covers all 180 IDs')
        if args.readme_shots:
            for path,name in (('/','home'),('/rankings','rankings'),('/competitions/past/1','protocol')):
                visit(path);page.screenshot(path=str(args.readme_shots/f'beta1-{name}.png'),full_page=True)
        for role,path in (('ROOT','/admin/audit'),('ADMIN','/admin/'),('OWNER','/cabinet/'),
                          ('JOCKEY','/cabinet/'),('VIEWER','/predictions/history')):
            context.clear_cookies()
            _, email, password = next(account for account in accounts if account[0] == role)
            visit('/auth/login');page.locator('[name=email]').fill(email);page.locator('[name=password]').fill(password)
            page.locator('button[type=submit]').click();page.wait_for_load_state('networkidle')
            visit(path)
        check(not errors, 'no JavaScript errors')
        browser.close()
    report = dict(checks=len(checks), passed=len(checks)-len(failures), failures=failures, javascript_errors=errors)
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))
    return int(bool(failures or errors))


if __name__ == '__main__':
    raise SystemExit(main())
