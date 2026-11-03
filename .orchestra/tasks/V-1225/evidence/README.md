# V-1225 source index

This index is the only evidence tracked in Git. Third-party texts, API JSON, PDF text and vendor READMEs are not mirrored here because origin is public.

The full raw set (22 files, byte-for-byte) is kept privately on the host:
`/home/kesha/orchestra/.orchestra/private/V-1225/evidence/`. The orchestrator wrote a SHA manifest there, `preserved-evidence.json`. The worker's hashes below can be compared against it.

Collected 2026-11-02, 11:08–11:15 UTC, from the hub with curl, without auth or cookies.

## Sources

| Source | URL | Revision / date | Fetch status |
|---|---|---|---|
| Hyra 2.0 post page (SPA shell) | https://hy.tencent.com/research/hyra2 | app-version `c0558753`, build 2026/10/30 18:12:43 | GET 200, 6894 B, no article text |
| Hyra 2.0 post, EN | `POST https://api.hunyuan.tencent.com/api/blog/publicDetail` body `{"id":0,"customUrl":"hyra2"}`, header `accept-language: en` (public endpoint used by the page's own bundle) | id 100127, publishVersionId `dbk4cck2c3mcfnhjdshg`, createdAt 2026-10-25T09:26:04Z, updatedAt 2026-11-02T08:25:15Z, content sha256 `03c939a9f924c202…` | 200, 42211 B |
| Hyra 2.0 post, ZH | same endpoint, `accept-language: zh` | publishVersionId `dbk4ajc2c3mettgisd5g`, content sha256 `93fba2948049a36c…` | 200, 34342 B |
| Hyra 1.0 post (context) | same endpoint, `{"id":0,"customUrl":"hyra"}` | publishVersionId `d9f3fsk2c3m25d51g55g`, display 2026-07-21 | 200, 37638 B |
| Results repository | https://github.com/Tencent-Hunyuan/Hyra-results | commit `d7bd6941bd1386df7a6dff5bc060141620c05f04` (2026-11-02T09:05:08Z): the codeload tarball's pax header matches the head of `commits/main.atom` | atom 200; codeload tar.gz 200 (25076410 B, 393 paths); REST `api.github.com/repos/...` 403 (unauthenticated rate limit) |
| Licenses | `LICENSE`, `AI4Science/hyinv/LICENSE`, `AI4Science/hyplm_flash/LICENSE` at that commit | Apache-2.0 for Tencent-authored materials; MIT for HyInv (ProteinMPNN © 2022 + HyInv 2026) and HyPLM | read from the tarball |
| Technical reports | `AI4Science/hyinv/HyInv_Technical_Report.pdf` (dated 2026-10-14), `AI4Science/hyplm_flash/HyPLM_Technical_Report.pdf` (2026-10-12), at that commit | text extracted with a stdlib scraper (spaces lost), used for keyword search only | read from the tarball |
| GitHub search | `api.github.com/search/repositories?q=org:Tencent-Hunyuan+hyra` and `?q=hyra+tencent` | `Tencent-Hunyuan/Hyra-results` created 2026-07-17; third-party `MrSteeeve/OpenHyra` (MIT) is not official and was not cloned | 200 |
| Telegram post AI-machinelearning 11266/11267 | — | — | not opened (secondary source) |

## Private raw files (sha256 at collection time)

Line references `L<n>` in `../report.md` point to `detail_en.content.md` (the `content` field of the EN response, verbatim).

Redaction in the redacted files: presigned COS query strings, which carry an access-key id (`q-ak=AKID…`), were replaced with `?[signed-query-removed]`.

| File | sha256 |
|---|---|
| detail_en.content.md | 354edea54c7658b05a2904614b993df668e13392a748aa7baf63460d46af94b6 |
| detail_en.redacted.json | c721a4d78bcd141211fe2f7cb970e7d4114565c2c76085753ba689265a62e2c9 |
| detail_zh.content.md | 46333536c89da69a9cf46550b11ec848ec7f79346117893329a174b97e2cdc1a |
| detail_zh.redacted.json | 83215e66e61e74b2a736c6a3bd2d4e7db44c1106737f6dc4d4dbd772e2eea4f3 |
| detail_hyra1_en.content.md | b4c7f3cf82334073c72e9122082d8dfa34545d02328b2c45fb8c2fe85f855feb |
| detail_hyra1_en.redacted.json | 798da380ba069317582fa05c675dbf471dcce8416de365c4ebce4782d5eda1ef |
| fetch_log.txt | 50a4d1d9bd9c9c39a939ca20ba3ad16b72ca1d23b7bf82010cdf8db22a3f4a49 |
| hr_commits.atom | 225c1814b99d2a2fc0d9484c9ed278a6401a63651f195a316d957e8794462ee1 |
| hyra-results_tar_listing.txt | 22662e03036e1c6fa250becb2f8da1e8048f07d3bbad5b3ae07c8ce749095c0a |
| hyinv.txt | 4e7e4ccef477d08fa1a17bcaff5ad4aed2252ac540aaf7d3fab663f894f06273 |
| hyplm.txt | 96dd5746392698518ebb017ca44fc572fc26946d19668f78643297a0d9e0f254 |
| hyra-results__README.md | d48f0b1cce0200ba9a374ece3333138ac42bb70a49acadab37b696e59d2e15df |
| hyra-results__LICENSE | ece6c7026732f576af3a909a117b321c9e8cfd96fc4d56e5229ff1a288dae087 |
| hyra-results__AI4AI__README.md | 0c6799a749c883e38225ccd9f9a9abec27542bdf0e7f61027793001219a79733 |
| hyra-results__AI4Science__hyinv__README.md | b44c6d0c4c7f73aaf920cf734670a8d4649df175c14a105afaf5e74172fd6891 |
| hyra-results__AI4Science__hyinv__LICENSE | 816fb3d74b232ce2348dc1e4d93e41564780985789bd01fd4a15369af99ce350 |
| hyra-results__AI4Science__hyplm_flash__README.md | db6ab273ef190a40199a5a8d17c474a2809fd9cedac6013c45ec7c06642542a3 |
| hyra-results__AI4Science__hyplm_flash__LICENSE | a0a9dc95e81d7a1374275195bccb72442e0126be826919b13ff67f52eb64a031 |
| gh_search_repositories_q_org_Tencent-Hunyuan_hyra.json | 5ce7db719061ca7511ef101920e1cb5a96256ada219cfe13da0051ced2ba5197 |
| gh_search_repositories_q_hyra_tencent.json | e9665ba54562e042b39519d4497571d75000620017c30c0a88346635bc139bd3 |
| gh_repos_Tencent-Hunyuan_hyra-results.json | f03f74f45d2b2a0759207ef9b557e87bd0a6d4062959018c0c6bf296e051dc55 |
| README.md (previous version of this file) | 306be01fe4634aa4327013be58f84ab82ae0bb448b69dccf6114341fd4052704 |
