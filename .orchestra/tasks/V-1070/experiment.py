"""Offline synthetic corpus and geometry/CPU experiment, research only."""
import hashlib
import json
import math
import resource
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops

TASK = Path(__file__).resolve().parent
SAMPLES = TASK / 'samples'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'

def font(size):
    return ImageFont.truetype(FONT, size)

def tokens(w, h, patch):
    return math.ceil(w / patch) * math.ceil(h / patch)

def claude_size(w, h, edge, budget):
    # Integer exhaustive long-edge search avoids the polling/while construct.
    # Same aspect-preserving fits contract as Anthropic's reference implementation.
    swap = h > w
    if swap:
        w, h = h, w
    ratio = w / h
    for x in range(w, 0, -1):
        y = max(round(x / ratio), 1)
        if math.ceil(x / 28)*28 <= edge and math.ceil(y / 28)*28 <= edge and tokens(x,y,28) <= budget:
            return (y,x) if swap else (x,y)
    raise AssertionError('no fitting size')

def astra(w, h, detail):
    if detail == 'low':
        s = min(1,512/w,512/h)
        w,h = round(w*s),round(h*s)
    if detail == 'high' and tokens(w,h,32) > 2500:
        s = math.sqrt(1024*2500/(w*h))
        s *= min(math.floor(w*s/32)/(w*s/32), math.floor(h*s/32)/(h*s/32))
        w,h = math.floor(w*s),math.floor(h*s)
    return {'pixels':[w,h], 'patches':tokens(w,h,32), 'tokens':math.ceil(tokens(w,h,32)*1.2)}

def make_sample(i, kind):
    dark = kind != 'document'
    bg = '#111827' if dark else '#fffdf7'
    fg = '#d9e4f2' if dark else '#20252b'
    im = Image.new('RGB',(1280,720), bg)
    d = ImageDraw.Draw(im)
    d.text((35,40), f'SYNTHETIC / {kind.upper()} / {i:02}', font=font(30), fill=fg)
    status = 'FAILED' if i % 2 else 'PASSED'
    date = f'2026-10-{i+10:02}'
    serial = f'Q{i:02}-O0I1-B8S5'
    details = [f'Build: {status}', f'Date: {date}', f'ID: {serial}']
    if kind == 'terminal':
        lines = ['worker$ uv run --frozen python -m pytest tests/test_queue.py -q',
                 'queue item accepted; sequence=42; elapsed=0.037s',
                 'AssertionError: expected 42, received 43', '1 failed, 27 passed in 2.14s']
        for k, line in enumerate(lines):
            d.text((40,125+k*32),line,font=font(18),fill=fg)
        d.rectangle((35,305,1240,400),outline='#526276')
    elif kind == 'dashboard':
        for k,(label,val,col) in enumerate([('Queued','18','#3ba2ed'),('Running','4','#41b583'),('Errors','1','#ed605b')]):
            x=40+k*410
            d.rounded_rectangle((x,115,x+380,260),radius=12,fill='#253246')
            d.text((x+20,135),label,font=font(20),fill=fg)
            d.text((x+20,180),val,font=font(36),fill=col)
        points=[(60,540),(200,510),(340,535),(480,475),(620,490),(760,430),(900,465),(1180,410)]
        d.line(points,fill='#50b5ee',width=4)
        d.text((40,575),'Overview: queue rising; one error; 4 running',font=font(18),fill=fg)
    else:
        d.text((40,130),'TEST EQUIPMENT RECORD — NO PERSONAL DATA',font=font(22),fill=fg)
        for k,line in enumerate(['Item               Quantity       State', 'Test sensor        12             checked', 'Panel adapter      03             pending']):
            d.text((40,190+k*38),line,font=font(20),fill=fg)
        d.line((35,315,1240,315), fill='#777777',width=2)
    # Selected fine details have explicit font sizes and exact expected strings.
    fields=[]
    for k,(text,size) in enumerate(zip(details,(16,12,10))):
        y=330+k*23
        d.text((50,y),text,font=font(size),fill=fg)
        fields.append({'text':text,'font_px':size,'bbox':[45,y-2,500,y+21]})
    d.text((40,660),'Synthetic data. Large layout and tiny identifiers tested separately.',font=font(15),fill=fg)
    path=SAMPLES/f'{i:02}-{kind}.png'
    im.save(path)
    return im, {'number':i,'kind':kind,'file':path.name,'fields':fields}

def main():
    SAMPLES.mkdir(exist_ok=True)
    print('Pillow',Image.__version__)
    print('font_sha256',hashlib.sha256(Path(FONT).read_bytes()).hexdigest())
    images=[]; truth=[]
    for i in range(1,13):
        kind=('terminal','dashboard','document')[(i-1)//4]
        im,gt=make_sample(i,kind); images.append(im); truth.append(gt)
    (TASK/'ground-truth.json').write_text(json.dumps(truth,indent=2))
    timing=[]; sheetmap=[]
    for start in range(0,12,4):
        for variant, cell, size, gap in [('full',1280,(2560,1440),0),('compact',780,(1568,886),8),('half',640,(1280,720),0)]:
            t0=time.perf_counter(); c0=time.process_time()
            sheet=Image.new('RGB',size,'#808080')
            for j,im in enumerate(images[start:start+4]):
                thumb=im.copy(); thumb.thumbnail((cell,math.ceil(cell*720/1280)),Image.Resampling.LANCZOS)
                x=(j%2)*(cell+gap); y=(j//2)*(thumb.height+gap)
                sheet.paste(thumb,(x,y))
                d=ImageDraw.Draw(sheet); d.rectangle((x,y,x+36,y+17),fill='#ffffff')
                d.text((x+3,y),str(start+j+1),font=font(14),fill='#000000')
                sheetmap.append({'variant':variant,'sheet':start//4+1,'number':start+j+1,'xy':[x,y],'pixels':list(thumb.size),'original':truth[start+j]['file']})
            name=f'sheet-{start//4+1}-{variant}.png'; sheet.save(SAMPLES/name)
            timing.append({'file':name,'wall_ms':(time.perf_counter()-t0)*1000,'cpu_ms':(time.process_time()-c0)*1000,'bytes':(SAMPLES/name).stat().st_size})
    # Pixel-identical rotation recovery and EXIF controls, no OCR inference here.
    angle_checks=[]
    for idx in (0,4,8):
        for angle in (0,90,180,270):
            rotated=images[idx].rotate(angle,expand=True)
            filename=f'rotation-{idx+1:02}-{angle}.png'; rotated.save(SAMPLES/filename)
            restored=rotated.rotate(-angle,expand=True)
            angle_checks.append({'source':idx+1,'ccw_angle':angle,'identical_after_inverse':ImageChops.difference(restored,images[idx]).getbbox() is None})
    Image.new('RGB',(1280,720),'white').save(SAMPLES/'blank.png')
    # Two EXIF cases: tagged JPEG and physically equivalent pixels without EXIF.
    exif=Image.Exif(); exif[274]=6
    images[8].rotate(90,expand=True).save(SAMPLES/'exif-tag6.jpg',exif=exif,quality=95)
    with Image.open(SAMPLES/'exif-tag6.jpg') as source:
        normalized=ImageOps.exif_transpose(source)
        normalized.save(SAMPLES/'exif-normalized.png')
        print('EXIF case',list(source.size),'->',list(normalized.size),'orientation_after',normalized.getexif().get(274))
    # Reproducible format comparison (not the browser's encoder).
    format_rows=[]
    for idx in (0,4,8):
        t0=time.perf_counter();c0=time.process_time()
        target=SAMPLES/f'{idx+1:02}-q90.webp';images[idx].save(target,quality=90,method=4)
        format_rows.append({'number':idx+1,'png_bytes':(SAMPLES/truth[idx]['file']).stat().st_size,'webp_bytes':target.stat().st_size,'pixels':list(images[idx].size),'wall_ms':(time.perf_counter()-t0)*1000,'cpu_ms':(time.process_time()-c0)*1000})
    geometry=[]
    for w,h,n in [(1280,720,12),(2560,1440,3),(1568,886,3),(1280,720,3),(1568,1568,3)]:
        row={'input':[w,h],'N':n}
        for label,edge,budget in [('claude_standard',1568,1568),('claude_high',2576,4784)]:
            cw,ch=claude_size(w,h,edge,budget)
            row[label]={'pixels':[cw,ch],'tokens_each':tokens(cw,ch,28),'tokens_total':n*tokens(cw,ch,28)}
        for detail in ('original','high','low'):
            row['astra_'+detail]=astra(w,h,detail)
            row['astra_'+detail]['total_tokens']=n*row['astra_'+detail]['tokens']
        row['legacy_area_div750_total']=n*w*h/750
        geometry.append(row)
    assert tokens(1000,1000,28)==1296
    assert claude_size(1920,1080,1568,1568)==(1456,819)
    assert claude_size(3840,2160,2576,4784)==(2576,1449)
    assert astra(1024,1024,'high')['tokens']==1229
    assert astra(2048,2048,'high')['tokens']==3000
    assert all(row['identical_after_inverse'] for row in angle_checks)
    result={'geometry':geometry,'sheet_timing':timing,'format':format_rows,'rotation_controls':angle_checks,
            'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    (TASK/'experiment.json').write_text(json.dumps(result,indent=2))
    (TASK/'sheet-map.json').write_text(json.dumps(sheetmap,indent=2))
    print(json.dumps(result,indent=2))
    manifest=[{'file':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(SAMPLES.iterdir()) if p.is_file()]
    (TASK/'sample-manifest.json').write_text(json.dumps(manifest,indent=2))
    print('PASS geometry reference examples; 12/12 inverse rotations exact; synthetic corpus generated')

if __name__=='__main__':
    main()
