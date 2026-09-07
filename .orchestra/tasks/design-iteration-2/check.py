from pathlib import Path
import json
from playwright.sync_api import sync_playwright

HERE=Path(__file__).parent
ROOT=HERE.resolve().parents[2]
path=ROOT/'artifacts/design-iteration-2/index.html'
results=[]
with sync_playwright() as w:
    b=w.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
    page=b.new_page(viewport={'width':1440,'height':1100},accept_downloads=True)
    page.set_default_timeout(5000)
    errors=[];remote=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('http:','https:')) else None)
    page.goto(path.as_uri(),wait_until='networkidle')
    assert page.locator('#metric-in').inner_text()=='120'
    assert page.locator('#metric-q').inner_text()=='36'
    assert page.locator('#metric-wait').inner_text()=='72'

    assert page.locator('link[rel="icon"][type="image/svg+xml"]').get_attribute('href').startswith('data:image/svg+xml,')
    assert page.locator('.spark,.queue-mini,[data-spark]').count()==0
    page.evaluate("flowLab.select('analysis',7)")
    assert '−20 /мин за 5 с' in page.locator('#change-in').inner_text()
    assert '−7 /мин за 5 с' in page.locator('#change-growth').inner_text()
    assert 'растёт медленнее' in page.locator('#growth-direction').inner_text()
    assert page.locator('#metric-delta').inner_text()=='12'
    assert page.locator('#rate-change-chart rect').count()==22
    assert page.locator('#growth-change-chart rect').count()==11
    page.evaluate("flowLab.select('analysis',0)")
    assert page.locator('#change-in').inner_text()=='Нет предыдущего отсчёта'
    assert '24 → 24,4' in page.locator('#change-q').inner_text()
    page.evaluate("flowLab.select('analysis',11)")

    assert page.evaluate('flowLab.samples.every(s=>Math.abs(s.incoming-s.output-s.delta)<1e-8)')
    for width in [1440,390]:
        page.set_viewport_size({'width':width,'height':1100})
        for view in ['network','flow','space','time']:
            page.locator('nav [data-view='+view+']').click()
            page.wait_for_timeout(160)
            assert not errors,errors
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(width,view)
            if view=='space':
                assert page.locator('body').get_attribute('data-webgl')=='ready'
            if width==1440:
                page.screenshot(path=str(HERE/(view+'.png')),full_page=True)
            results.append({'view':view,'width':width,'render':'pass'})
    page.set_viewport_size({'width':1440,'height':1100})
    page.locator('nav [data-view=network]').click()
    box=page.locator('#rate-chart').bounding_box()
    page.mouse.move(box['x']+box['width']*.12,box['y']+box['height']*.5)
    assert page.locator('#metric-in').inner_text()=='100'
    assert page.locator('#chart-tooltip').is_visible()
    page.locator('#network-svg [data-node=search] rect').first.hover()
    assert 'Поиск справляется' in page.locator('#inspector').inner_text()
    page.locator('nav [data-view=flow]').click()
    page.locator('#flow-svg g[data-node=analysis] rect').hover()
    assert page.locator('#float-tooltip').is_visible()
    tip=page.locator('#float-tooltip').bounding_box()
    assert tip['x']>=0 and tip['y']>=0 and tip['x']+tip['width']<=1440
    page.mouse.move(0,0)
    page.locator('nav [data-view=space]').click()
    box=page.locator('#space-canvas').bounding_box()
    before=page.locator('body').get_attribute('data-camera')
    page.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.7)
    page.mouse.down();page.mouse.move(box['x']+box['width']*.5+120,box['y']+box['height']*.7+20,steps=8);page.mouse.up()
    page.wait_for_timeout(400)
    assert page.locator('body').get_attribute('data-camera')!=before
    before_zoom=page.locator('body').get_attribute('data-camera').split(',')[2]
    page.mouse.wheel(0,-120);page.wait_for_timeout(120)
    assert page.locator('body').get_attribute('data-camera').split(',')[2]!=before_zoom
    page.locator('nav [data-view=time]').click()
    cell=page.locator('#heat-svg [data-node=export][data-index="3"] rect').bounding_box()
    page.mouse.move(cell['x']+cell['width']/2,cell['y']+cell['height']/2)
    assert page.locator('body').get_attribute('data-index')=='3'
    assert 'Экспорт справляется' in page.locator('#inspector').inner_text()
    page.locator('nav [data-view=network]').click()
    page.locator('[data-vote=yes]').click();page.locator('#comment').fill('проверка сохранения')
    page.reload(wait_until='networkidle')
    assert page.locator('#comment').input_value()=='проверка сохранения'
    with page.expect_download() as d:page.locator('#export').click()
    payload=json.loads(Path(d.value.path()).read_text())
    assert payload['preferences']['network']['vote']=='yes'
    page.evaluate("localStorage.removeItem('design-iteration-2')")
    page.emulate_media(reduced_motion='reduce')
    page.locator('nav [data-view=space]').click()
    assert page.locator('body').get_attribute('data-webgl')=='ready'
    assert not remote,remote
    assert not errors,errors
    b.close()
(HERE/'checks.json').write_text(json.dumps({'renders':results,'errors':errors,'network':remote,'interactions':'linked hover, inspector, tooltip, 3D drag and zoom, heat map, saved votes/export, reduced motion passed'},ensure_ascii=False,indent=2))
print('8 renders passed; linked hover, calculations, 3D drag/zoom, votes/export verified; no network or JS errors.')
