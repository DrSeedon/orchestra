# Review memory

- Для multi-field protocol request общий `invalid params` не доказывает отказ конкретного поля. Перед schema fallback исполнять контрпримеры с тем же marker для остальных полей и требовать явный target-field discriminator.
