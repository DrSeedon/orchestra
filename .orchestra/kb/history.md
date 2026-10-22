# История источников: Git вместо папок-свалок

Полный снимок до очистки: `68d32a4b4a6ad0130d08894791f68c5e84152c2c`. Коммит достижим из main и содержит прежние workers,
tasks, archive, guides, artifacts. ```bash
git grep -n -i -F '<точный якорь>' 68d32a4b4a6ad0130d08894791f68c5e84152c2c -- .orchestra/workers .orchestra/tasks .orchestra/archive .orchestra/guides .orchestra/artifacts
git show 68d32a4b4a6ad0130d08894791f68c5e84152c2c:.orchestra/tasks/<id>/<file>
```

Это адреса исходников, не действующие инструкции или правила ведения KB.
