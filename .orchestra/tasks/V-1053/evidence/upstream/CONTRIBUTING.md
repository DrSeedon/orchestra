# Contributing

Thank you for wanting to make `tour` better. Requests, bug reports and ideas are very welcome, as issues.

**We don't accept pull requests.** Please open an [issue](https://github.com/init-co-jp/diff-tour/issues/new/choose) instead, and we will write the change ourselves. `tour` hands other people's repositories to an LLM, so every change goes through the same review of what the LLM can read and do, and the prompts and translations are tuned together. Writing it ourselves is faster than fitting a pull request into that, for you and for us.

What helps the most in an issue:

- **A bug:** the output of `tour --version`, your OS, which LLM you use and its version (`claude --version` and the like), what you ran, and what happened. Remove anything private from logs first.
- **A feature or another LLM:** what you are trying to do, and where `tour` gets in the way. A link to the tool's docs helps.
- **A language:** which language, and for which readers (for Chinese, for example: mainland China, Taiwan or Hong Kong). If you can read a draft and tell us what sounds unnatural, say so. That review is the part we cannot do without you.

You can write in English or Japanese.

## Security

If you find a way for the LLM to write files, run commands, reach the network or read outside the change, please do not open a public issue. Report it privately from the [Security tab](https://github.com/init-co-jp/diff-tour/security) (Report a vulnerability).

## Forks

`tour` is MIT-licensed. You are free to fork it and change it for your own use.
