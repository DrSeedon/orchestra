## Summary

Reviewed the complete diff between the pinned commits. The Docker image omits required prompt and template files, which breaks normal Orchestra behavior.

## Findings

### Blocking

- **Markdown assets are excluded from the image.** The `*.md` rule in [.dockerignore](/home/kesha/v918-work/v918-clean-10.r0-t0btie15/.dockerignore:18) matches Markdown files throughout the build context, including pipeline prompts and templates. `COPY pipelines/` therefore copies manifests without their prompt layers and templates, and `COPY app/` omits the legacy prompts. Pipeline prompts are silently assembled from whichever files remain, while role docs cannot load their templates. The service may start, but agent behavior and pipeline workflows are incomplete. Remove this broad ignore rule or explicitly include the required assets.

### Suggestion

- **The container has no project repositories mounted.** [docker-compose.yml](/home/kesha/v918-work/v918-clean-10.r0-t0btie15/docker-compose.yml:6) mounts only `data`, `worktrees`, `.env`, and git config. Session creation requires a working directory that exists inside the container; host project paths will not exist there, and the mounted `worktrees` directory alone does not provide a repository. Mount the projects directory or document the expected in-container repository setup.

## Verdict

NEEDS WORK