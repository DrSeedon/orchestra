from pathlib import Path
HERE=Path(__file__).parent
ROOT=HERE.resolve().parents[2]
previous=ROOT/'.orchestra/tasks/design-skill-gallery'
three=(previous/'three-r128.min.js').read_text().replace('//# sourceMappingURL=three.min.js.map','')
license=(previous/'THREE-LICENSE.txt').read_text()
doc=(HERE/'shell.html').read_text().replace('/*STYLE*/',(HERE/'style.css').read_text()).replace('/*THREE*/','/* '+license+' */\n'+three).replace('/*APP*/',(HERE/'app.js').read_text())
out=ROOT/'artifacts/design-iteration-2/index.html'
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(doc)
print(out)
