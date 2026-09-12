import time

async def calculate(label, expression, expected):
    started = time.time()
    value = await agent(
        f'Вычисли {expression}. Верни только JSON с ключом answer, целое число.',
        model='luna',
        schema={'type': 'object', 'properties': {'answer': {'type': 'integer', 'const': expected}},
                'required': ['answer'], 'additionalProperties': False},
        label=label, timeout=180,
    )
    assert value is not None, f'{label} failed'
    return {'label': label, 'started': started, 'ended': time.time(), 'value': value.data}

result = await parallel([
    lambda: calculate('a', '173 * 29', 5017),
    lambda: calculate('b', '211 * 37', 7807),
])
assert max(x['started'] for x in result) < min(x['ended'] for x in result)
log(str(result))
