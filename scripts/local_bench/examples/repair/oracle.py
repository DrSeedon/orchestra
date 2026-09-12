from calc import total
for values in ([], [0], [1], [-3, 4], [2, 3, 5]):
    assert total(values) == sum(values), values
print('5 checks passed')
