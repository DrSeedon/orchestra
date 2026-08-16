# impl-review-model

- Prompt policy files cannot copy versioned model IDs owned by `pipeline.yaml`;
  `scripts/check_pipeline_manifest.py --check` rejects them. Use registered short aliases in
  prompt examples and keep canonical-ID validation in runtime tests.
