"""Run only the studied local classifier; no vision provider or model judge."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import statistics
import sys
import time

TASK=Path(__file__).resolve().parent
sys.path.insert(0,str(TASK/'deps'))
t0=time.perf_counter(); c0=time.process_time()
import cv2
import numpy as np
from rapid_orientation import RapidOrientation
import rapid_orientation.main as rapid_module
import onnxruntime
print('import_wall_ms',(time.perf_counter()-t0)*1000,'cpu_ms',(time.process_time()-c0)*1000)
versions={p:importlib.metadata.version(p) for p in ['rapid-orientation','onnxruntime','numpy','opencv-python','Pillow','PyYAML','flatbuffers','protobuf','packaging']}
print('versions',versions)
package=Path(rapid_module.__file__).parent
model=package/'models/rapid_orientation.onnx'
print('model_bytes',model.stat().st_size,'sha256',hashlib.sha256(model.read_bytes()).hexdigest())
# Preserve the exact version's source, rather than assuming GitHub main matches the wheel.
for rel in ['main.py','utils/preprocess.py','utils/infer_engine.py','config.yaml']:
    target=TASK/'sources'/('rapid-0.0.11-'+rel.replace('/','-'))
    target.write_bytes((package/rel).read_bytes())
t0=time.perf_counter(); c0=time.process_time()
engine=RapidOrientation(cfg_path=TASK/'rapid-experiment.yaml')
init={'wall_ms':(time.perf_counter()-t0)*1000,'cpu_ms':(time.process_time()-c0)*1000}
print('initialization',init)
rows=[]
for source in (1,5,9):
    for angle in (0,90,180,270):
        path=TASK/'samples'/f'rotation-{source:02}-{angle}.png'
        image=cv2.imread(str(path))
        times=[]; cpu=[]; labels=[]
        for repeat in range(3):
            t0=time.perf_counter(); c0=time.process_time()
            label,_=engine(image)
            times.append((time.perf_counter()-t0)*1000);cpu.append((time.process_time()-c0)*1000);labels.append(label)
        batch=engine.preprocess(image)
        probs=engine.session(batch)[0]
        top=np.sort(probs[0])
        # Infer the label convention from recovery against original pixels: the
        # returned label is the CCW correction, inverse to physical CCW rotation.
        original=cv2.imread(str(TASK/'samples'/f'rotation-{source:02}-0.png'))
        restored=np.rot90(image,int(labels[0])//90)
        row={'source':source,'physical_ccw_angle':angle,'expected_label':str((-angle)%360),'labels':labels,
             'correct':bool(np.array_equal(restored,original)),'wall_ms':times,'cpu_ms':cpu,
             'raw_first_output':probs[0].tolist(),'output_sum':float(probs[0].sum()),
             'top_score':float(top[-1]),'top_margin':float(top[-1]-top[-2]),
             'batch_crops_identical':bool(np.array_equal(batch[0],batch[1]) and np.array_equal(batch[1],batch[2]))}
        rows.append(row)
        print(json.dumps(row))
blank=cv2.imread(str(TASK/'samples'/'blank.png'))
blank_label,blank_elapsed=engine(blank)
blank_probs=engine.session(engine.preprocess(blank))[0][0].tolist()
print('blank',blank_label,blank_probs)
print('model_metadata',engine.session.session.get_modelmeta().custom_metadata_map)
result={'versions':versions,'model_bytes':model.stat().st_size,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
        'init':init,'cases':rows,'N_unique':12,'N_calls':36,'correct':sum(x['correct'] for x in rows),
        'median_wall_ms':statistics.median(t for x in rows for t in x['wall_ms']),
        'median_cpu_ms':statistics.median(t for x in rows for t in x['cpu_ms']),
        'blank':{'label':blank_label,'raw_output':blank_probs,'elapsed_ms':blank_elapsed*1000},
        'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
(TASK/'rapid-results.json').write_text(json.dumps(result,indent=2))
print('SUMMARY',json.dumps({k:v for k,v in result.items() if k not in ['cases','versions']}))
