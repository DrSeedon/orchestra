# История источников: Git вместо папок-свалок

Полный снимок до очистки: `9a1735f1695519a445f393802c2154bd37337e38`. Коммит достижим из main и содержит прежние workers,
tasks, archive, guides, artifacts. ```bash
git grep -n -i -F '<точный якорь>' 9a1735f1695519a445f393802c2154bd37337e38 -- .orchestra/workers .orchestra/tasks .orchestra/archive .orchestra/guides .orchestra/artifacts
git show 9a1735f1695519a445f393802c2154bd37337e38:.orchestra/tasks/<id>/<file>
```

Это адреса исходников, не действующие инструкции или правила ведения KB.
