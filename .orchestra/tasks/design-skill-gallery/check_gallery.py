from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'artifacts/design-skill-gallery'
HERE = Path(__file__).parent
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
    page=browser.new_page(viewport={'width':1280,'height':950},accept_downloads=True)
    errors=[]
    remote=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('http:','https:')) else None)
    for f in sorted(OUT.glob('*.html')):
        for width in [1280,390]:
            errors.clear(); remote.clear()
            page.set_viewport_size({'width':width,'height':950})
            page.goto(f.as_uri(),wait_until='networkidle')
            overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            assert not overflow,(f.name,width,'horizontal overflow')
            assert not errors,(f.name,width,errors)
            assert not remote,(f.name,width,remote)
            if width==1280:
                page.screenshot(path=str(HERE/(f.stem+'.png')))
            results.append({'file':f.name,'width':width,'errors':list(errors),'network':list(remote),'overflow':overflow})
    page.set_viewport_size({'width':1280,'height':950})
    for name in ['01-apple','03-global']:
        page.goto((OUT/(name+'.html')).as_uri())
        page.get_by_role('button',name='Задачи',exact=True).click()
        assert page.locator('#tasks').is_visible()
        assert not page.locator('#overview').is_visible()
    page.goto((OUT/'07-eli5.html').as_uri())
    page.locator('#arrival').fill('10')
    page.locator('#arrival').dispatch_event('input')
    assert page.locator('.waiting').count()==6
    page.locator('#arrival').fill('1')
    page.locator('#arrival').dispatch_event('input')
    assert page.locator('.empty').count()==3
    page.goto((OUT/'08-playground.html').as_uri())
    page.locator('#preset').select_option('soft')
    assert '28 px' in page.locator('#prompt').inner_text()
    assert page.locator('#preview .metric').first.evaluate('(e)=>getComputedStyle(e).padding')=='28px'
    page.goto((OUT/'09-three.html').as_uri(),wait_until='networkidle')
    assert page.locator('body').get_attribute('data-webgl')=='ready'
    page.evaluate('scrollTo(0,1500)')
    page.wait_for_timeout(500)
    page.screenshot(path=str(HERE/'09-three-scrolled.png'))
    page.emulate_media(reduced_motion='reduce')
    page.reload(wait_until='networkidle')
    assert page.locator('body').get_attribute('data-webgl')=='ready'
    page.emulate_media(reduced_motion='no-preference')
    page.goto((OUT/'10-cro.html').as_uri())
    page.get_by_role('button',name='Открыть учебный обзор').click()
    assert page.locator('#opened').is_visible()
    page.goto((OUT/'index.html').as_uri(),wait_until='networkidle')
    for i in range(10):
        errors.clear()
        page.locator('nav button').nth(i).click()
        page.frame_locator('#frame').locator('h1').wait_for()
        assert not errors,errors
    page.locator('nav button').nth(0).click()
    page.get_by_role('button',name='Оставить',exact=True).click()
    page.locator('#comment').fill('Тест сохранения оценки')
    page.reload(wait_until='networkidle')
    assert page.locator('#comment').input_value()=='Тест сохранения оценки'
    with page.expect_download() as d:
        page.get_by_role('button',name='Скачать мои оценки').click()
    downloaded=d.value.path()
    votes=json.loads(Path(downloaded).read_text())
    assert votes['samples'][0]['vote']=='yes'
    assert votes['samples'][0]['comment']=='Тест сохранения оценки'
    page.evaluate("localStorage.removeItem('design-gallery-v1')")
    page.reload(wait_until='networkidle')
    page.emulate_media(media='print')
    page.goto((OUT/'01-apple.html').as_uri())
    page.pdf(path=str(HERE/'apple-print.pdf'),format='A4',print_background=True)
    page.emulate_media(media='screen',color_scheme='dark')
    page.goto((OUT/'02-local.html').as_uri())
    assert page.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(24, 24, 24)'
    page.screenshot(path=str(HERE/'02-local-dark.png'))
    browser.close()
(HERE/'checks.json').write_text(json.dumps({'renders':results,'interactions':'passed','offline':'passed','print':'rendered apple-print.pdf','reduced_motion':'WebGL static mode loads','votes':'persist and export verified'},indent=2))
print(f'{len(results)} viewport renders passed; tabs, slider boundaries, presets, WebGL, embedded samples, vote persistence/export, print and dark mode checked.')
