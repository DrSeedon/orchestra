package render

import (
	"errors"
	"fmt"

	"github.com/init-co-jp/diff-tour/internal/schema"
)

// Check verifies that the files, lines, hunks and schemas a tour points to actually exist.
// Messages are in English so they can be passed as-is when asking the LLM to fix a generated tour.
func Check(ctx Ctx) []string {
	var problems []string
	add := func(step int, title, format string, args ...any) {
		problems = append(problems, fmt.Sprintf("step %d (%q): %s", step, title, fmt.Sprintf(format, args...)))
	}
	steps := ctx.Tour.Steps()
	for i, step := range steps {
		n := i + 1
		if step.Question && i == len(steps)-1 {
			add(n, step.Title, "a question step must be followed by a step with the answer")
		}
		for _, b := range step.Blocks {
			switch {
			case b.Code != nil:
				ref := ctx.Ref(b.Code.At)
				src := ctx.Repo.Show(ref, b.Code.File)
				if src == nil {
					add(n, step.Title, "code: file %s does not exist at %s", b.Code.File, b.Code.At)
					continue
				}
				l0, l1 := b.Code.Lines[0], b.Code.Lines[1]
				if l0 < 1 || l1 > len(src) || l0 > l1 {
					add(n, step.Title, "code: lines %d-%d are out of range for %s (%d lines)", l0, l1, b.Code.File, len(src))
				}
				if s := b.Code.Show; s != nil && (s[0] < 1 || s[1] > len(src) || s[0] > s[1] || s[0] > l0 || s[1] < l1) {
					add(n, step.Title, "code: show %d-%d must be within the file (%d lines) and contain lines %d-%d", s[0], s[1], len(src), l0, l1)
				}
				s0, s1 := max(1, l0-2), min(len(src), l1+2)
				if s := b.Code.Show; s != nil {
					s0, s1 = s[0], s[1]
				}
				for _, m := range b.Code.Marks {
					if m.Line < s0 || m.Line > s1 {
						add(n, step.Title, "code: mark on line %d is outside the lines shown (%d-%d) of %s", m.Line, s0, s1, b.Code.File)
					}
				}
			case b.Diff != nil:
				if _, msg := pickHunks(ctx, b.Diff); msg != "" {
					hunks, _ := ctx.Repo.Diff(ctx.Tour.Base, ctx.Tour.Head, b.Diff.File)
					add(n, step.Title, "diff: %s has %d hunks; hunks %v are invalid or the file has no changes", b.Diff.File, len(hunks), b.Diff.Hunks)
				}
			case b.Files != nil:
				changed := map[string]bool{}
				for _, f := range ctx.Repo.FileStats(ctx.Tour.Base, ctx.Tour.Head) {
					changed[f.File] = true
				}
				for _, r := range b.Files.Roles {
					if !changed[r.File] {
						add(n, step.Title, "files: %s is not one of the changed files", r.File)
					}
				}
			case b.Schema != nil:
				before, errB := schema.Load(ctx.Repo, ctx.Ref("base"), b.Schema.Migrations)
				after, errA := schema.Load(ctx.Repo, ctx.Ref("head"), b.Schema.Migrations)
				if errB != nil || errA != nil {
					add(n, step.Title, "schema: cannot load migrations in %s: %v", b.Schema.Migrations, errors.Join(errB, errA))
					continue
				}
				for _, t := range b.Schema.Tables {
					if before[t] == nil && after[t] == nil {
						add(n, step.Title, "schema: table %s exists neither before nor after the change", t)
					}
				}
			}
		}
	}
	return problems
}
