package generate

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"text/template"

	"github.com/init-co-jp/diff-tour/internal/tour"
)

// Question is a reader's question about one step of a tour.
type Question struct {
	Tour *tour.Tour
	// The step the reader was looking at (counting across chapters).
	Index int
	Text  string
}

// Answer has the reader's question answered as one or two steps to insert after the current step.
// It reads the same files a tour is written from, so it can show code that the tour did not.
func Answer(ctx context.Context, backend Backend, req Request, q Question, workDir string, progress func(Progress)) ([]tour.Step, Stats, error) {
	var stats Stats
	ws, err := PrepareWorkspace(req.Repo, req.Base, req.Head, workDir)
	if err != nil {
		return nil, stats, err
	}
	defer ws.Remove()
	if err := writeLessons(ws.Dir); err != nil {
		return nil, stats, err
	}
	whole, err := json.MarshalIndent(q.Tour, "", "  ")
	if err != nil {
		return nil, stats, err
	}
	if err := os.WriteFile(filepath.Join(ws.Dir, "tour.json"), whole, 0o644); err != nil {
		return nil, stats, err
	}
	prompt, err := askPrompt(req, q)
	if err != nil {
		return nil, stats, err
	}

	onEvent := func(e Event) { progress(Progress{Event: &e, Phase: "reading"}) }
	progress(Progress{Phase: "reading"})
	res, err := backend.Run(ctx, ws.Dir, prompt, onEvent)
	stats.CostUSD += res.CostUSD
	if err != nil {
		return nil, stats, err
	}
	t, err := settle(ctx, backend, req, ws.Dir, res.Text, &stats, progress, onEvent)
	if err != nil {
		return nil, stats, err
	}
	var steps []tour.Step
	for _, c := range t.Chapters {
		steps = append(steps, c.Steps...)
	}
	if len(steps) == 0 {
		return nil, stats, &InvalidTourError{Problems: []string{"the answer has no steps"}}
	}
	for i := range steps {
		steps[i].Question, steps[i].Asks = false, nil
	}
	steps[0].Asked = q.Text
	return steps, stats, nil
}

func askPrompt(req Request, q Question) (string, error) {
	src, err := prompts.ReadFile("prompts/ask.md")
	if err != nil {
		return "", err
	}
	tmpl, err := template.New("ask").Parse(string(src))
	if err != nil {
		return "", err
	}
	var b strings.Builder
	if err := tmpl.Execute(&b, map[string]string{"LanguageRule": languageRules[req.Lang]}); err != nil {
		return "", err
	}

	steps := q.Tour.Steps()
	b.WriteString("\n\n## ツアーの手順\n")
	for i, s := range steps {
		mark := "  "
		if i == q.Index {
			mark = "▶ "
		}
		fmt.Fprintf(&b, "%s%d. %s / %s\n", mark, i+1, s.ChapterTitle, s.Title)
	}
	current, err := json.MarshalIndent(steps[q.Index].Step, "", "  ")
	if err != nil {
		return "", err
	}
	fmt.Fprintf(&b, "\n## いまの手順（%d 番目）\n%s\n", q.Index+1, current)
	fmt.Fprintf(&b, "\n## 読者の質問\n%s\n", q.Text)
	fmt.Fprintf(&b, "\n対象の変更: base は `%s`、head は `%s`。JSON の base と head にはこの名前をそのまま書く。\n", req.Base, req.Head)
	b.WriteString("\n" + readPrompt("format.md") + "\n\n" + readPrompt("ask-output.md"))
	return b.String(), nil
}
