# skillstate-bench

- В benchmark с exact-code grader сначала доставлять модели полный enum/normalizer vocabulary и проверять rendered prompt; скрытые gold-коды дали семантически верному ответу ложный `model_error` в #430.
- В benchmark с выбранной когортой oracle обязан сам перечислить eligible census, перечитать фактические source bytes и пересчитать ranking/top-k; проверка только формы и присланных digest допускает произвольную «валидную» выборку (#430).
- В репликации опубликованного протокола сначала воспроизводить его model-visible contract дословно; provider enforcement, которого нет в источнике, — отдельная вариация, а не беззвучное «улучшение» baseline (#430: Structured Outputs сломал открытый patch до model call).
