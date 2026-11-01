// Package tour defines the tour data format.
package tour

import (
	"encoding/json"
	"fmt"
	"os"
	"slices"
)

// Version is the tour format version this tool can read.
const Version = 1

// Basis is the grounds for an explanation.
type Basis string

const (
	Fact     Basis = "fact"     // verified (backed by code, tests or commit messages)
	Inferred Basis = "inferred" // can be read from the structure of the code
	Opinion  Basis = "opinion"  // a senior's view (general wisdom, not verified in this repository)
)

type Location struct {
	File string `json:"file"`
	Line int    `json:"line"`
	// Which revision of the code: "base" or "head" (default).
	At string `json:"at,omitempty"`
}

type CodeRef struct {
	File string `json:"file"`
	At   string `json:"at,omitempty"`
	// Lines to highlight [start, end].
	Lines [2]int `json:"lines"`
	// Range to display. Defaults to 2 lines around the highlighted lines.
	Show *[2]int `json:"show,omitempty"`
	// A side note such as "unchanged".
	Note string `json:"note,omitempty"`
	// Short notes attached to single lines, drawn under them.
	Marks []Mark `json:"marks,omitempty"`
}

// Mark is a short note attached to one line of code.
type Mark struct {
	Line int    `json:"line"`
	Text string `json:"text"`
}

// Flow is a diagram of how processing flows from one place to the next, drawn by the tool.
type Flow struct {
	Nodes []FlowNode `json:"nodes"`
}

type FlowNode struct {
	Label string `json:"label"`
	// "changed", "new", "same" (default) or "external" (a database or another service).
	Kind string `json:"kind,omitempty"`
	// Shown beside the box.
	Note string `json:"note,omitempty"`
	// The label of the arrow to the next node.
	Next string `json:"next,omitempty"`
	// Starts a separate flow (another request, a timer), so no arrow comes from the node before.
	Start bool `json:"start,omitempty"`
}

// Timeline shows what happens over time on several lanes (requests, processes, the database), drawn by the tool.
type Timeline struct {
	Lanes  []string        `json:"lanes"`
	Events []TimelineEvent `json:"events"`
}

type TimelineEvent struct {
	// The lane where it happens.
	Lane string `json:"lane"`
	// For a message, the lane it goes to.
	To   string `json:"to,omitempty"`
	Text string `json:"text"`
	// "ok", "bad" or "note".
	Mark string `json:"mark,omitempty"`
}

// FileMap is a map of the changed files. The tool reads the files and their sizes from git;
// Roles only says how to read them.
type FileMap struct {
	Roles []FileRole `json:"roles,omitempty"`
}

// FileRole says how a changed file should be read, for the file map.
type FileRole struct {
	File string `json:"file"`
	// "core", "mechanical", "test", "config" or "docs".
	Role string `json:"role"`
	Note string `json:"note,omitempty"`
}

type DiffRef struct {
	File string `json:"file"`
	// Indexes of the hunks to show (0-based). Defaults to all.
	Hunks []int `json:"hunks,omitempty"`
}

// Snippet is code that is not in the repository. Label must always say so.
type Snippet struct {
	Label string `json:"label"`
	Lang  string `json:"lang,omitempty"`
	Text  string `json:"text"`
}

type SchemaRef struct {
	// Directory holding the migration SQL (applied in file-name order).
	Migrations string `json:"migrations"`
	// Tables to show. Defaults to every table that changed.
	Tables []string `json:"tables,omitempty"`
	// Columns to highlight ("table.column").
	Focus []string `json:"focus,omitempty"`
}

type Rows struct {
	// A short tag showing where the table came from. Defaults to "example" (data made up for the explanation).
	Tag   string     `json:"tag,omitempty"`
	Label string     `json:"label"`
	Head  []string   `json:"head"`
	Data  [][]string `json:"data"`
	// Columns added by this change.
	Added []string `json:"added,omitempty"`
}

type Table struct {
	Head []string   `json:"head"`
	Rows [][]string `json:"rows"`
}

// Block is one part of a step. It holds exactly one kind of item.
type Block struct {
	P        *string    `json:"p,omitempty"`
	Basis    Basis      `json:"basis,omitempty"`
	Quote    *string    `json:"quote,omitempty"`
	List     []string   `json:"list,omitempty"`
	Pre      *string    `json:"pre,omitempty"`
	Table    *Table     `json:"table,omitempty"`
	Code     *CodeRef   `json:"code,omitempty"`
	Diff     *DiffRef   `json:"diff,omitempty"`
	Snippet  *Snippet   `json:"snippet,omitempty"`
	Schema   *SchemaRef `json:"schema,omitempty"`
	Rows     *Rows      `json:"rows,omitempty"`
	Flow     *Flow      `json:"flow,omitempty"`
	Timeline *Timeline  `json:"timeline,omitempty"`
	Files    *FileMap   `json:"files,omitempty"`
	Target   bool       `json:"target,omitempty"`
}

// IsVisual reports whether the block is laid out on the left, like code or data.
func (b Block) IsVisual() bool {
	return b.Code != nil || b.Diff != nil || b.Snippet != nil || b.Schema != nil || b.Rows != nil ||
		b.Flow != nil || b.Timeline != nil || b.Files != nil
}

func (b Block) kinds() int {
	n := 0
	for _, set := range []bool{b.P != nil, b.Quote != nil, b.List != nil, b.Pre != nil, b.Table != nil, b.Code != nil,
		b.Diff != nil, b.Snippet != nil, b.Schema != nil, b.Rows != nil, b.Flow != nil, b.Timeline != nil, b.Files != nil, b.Target} {
		if set {
			n++
		}
	}
	return n
}

type Step struct {
	Title string `json:"title"`
	// A step that shows only the question. The answer goes in the next step.
	Question bool `json:"question,omitempty"`
	// Questions a reader is likely to have at this step, offered when they press `?`.
	Asks []string `json:"asks,omitempty"`
	// Set on a step that answers a reader's question: the question.
	Asked string `json:"asked,omitempty"`
	// Where `o` opens. Defaults to the first code block.
	Open   *Location `json:"open,omitempty"`
	Blocks []Block   `json:"blocks"`
}

type Chapter struct {
	Title string `json:"title"`
	Steps []Step `json:"steps"`
}

type Tour struct {
	Version  int       `json:"version"`
	Title    string    `json:"title"`
	Base     string    `json:"base"`
	Head     string    `json:"head"`
	Chapters []Chapter `json:"chapters"`
}

type FlatStep struct {
	Step
	Chapter      int
	ChapterTitle string
}

func (t *Tour) Steps() []FlatStep {
	var out []FlatStep
	for i, c := range t.Chapters {
		for _, s := range c.Steps {
			out = append(out, FlatStep{s, i, c.Title})
		}
	}
	return out
}

// DropRevealingAsks removes the suggested questions on a question step and on the step just before it,
// since their wording would give away the answer the reader is asked to think about.
func (t *Tour) DropRevealingAsks() {
	var steps []*Step
	for i := range t.Chapters {
		for j := range t.Chapters[i].Steps {
			steps = append(steps, &t.Chapters[i].Steps[j])
		}
	}
	for i, s := range steps {
		if s.Question {
			s.Asks = nil
			if i > 0 {
				steps[i-1].Asks = nil
			}
		}
	}
}

func Load(path string) (*Tour, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var t Tour
	if err := json.Unmarshal(b, &t); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if err := t.Validate(); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return &t, nil
}

// Validate checks for format errors. Whether the referenced files and lines exist is checked at display time.
func (t *Tour) Validate() error {
	if t.Version != Version {
		return fmt.Errorf("unsupported version %d (expected %d)", t.Version, Version)
	}
	if t.Base == "" || t.Head == "" {
		return fmt.Errorf("base and head are required")
	}
	if len(t.Steps()) == 0 {
		return fmt.Errorf("no steps")
	}
	for ci, c := range t.Chapters {
		for si, s := range c.Steps {
			if s.Title == "" {
				return fmt.Errorf("chapter %d step %d: title is required", ci+1, si+1)
			}
			for bi, b := range s.Blocks {
				if b.kinds() != 1 {
					return fmt.Errorf("chapter %d step %d block %d: a block must have exactly one kind", ci+1, si+1, bi+1)
				}
				if b.Basis != "" && b.P == nil {
					return fmt.Errorf("chapter %d step %d block %d: basis is only for p", ci+1, si+1, bi+1)
				}
				switch b.Basis {
				case "", Fact, Inferred, Opinion:
				default:
					return fmt.Errorf("chapter %d step %d block %d: unknown basis %q", ci+1, si+1, bi+1, b.Basis)
				}
				if err := b.checkDiagram(); err != nil {
					return fmt.Errorf("chapter %d step %d block %d: %w", ci+1, si+1, bi+1, err)
				}
			}
		}
	}
	return nil
}

// MaxLanes is the most lanes a timeline can have and still fit beside the text.
const MaxLanes = 4

func oneOf(v string, allowed ...string) bool {
	return slices.Contains(allowed, v)
}

// checkDiagram checks the shape of the blocks the tool draws.
func (b Block) checkDiagram() error {
	switch {
	case b.Flow != nil:
		if len(b.Flow.Nodes) == 0 {
			return fmt.Errorf("flow: nodes is empty")
		}
		for _, n := range b.Flow.Nodes {
			if n.Label == "" {
				return fmt.Errorf("flow: every node needs a label")
			}
			if !oneOf(n.Kind, "", "same", "changed", "new", "external") {
				return fmt.Errorf("flow: unknown kind %q (use same, changed, new or external)", n.Kind)
			}
		}
	case b.Timeline != nil:
		tl := b.Timeline
		if len(tl.Lanes) == 0 || len(tl.Lanes) > MaxLanes {
			return fmt.Errorf("timeline: needs 1 to %d lanes, has %d", MaxLanes, len(tl.Lanes))
		}
		if len(tl.Events) == 0 {
			return fmt.Errorf("timeline: events is empty")
		}
		for _, e := range tl.Events {
			if !slices.Contains(tl.Lanes, e.Lane) {
				return fmt.Errorf("timeline: lane %q is not one of %q", e.Lane, tl.Lanes)
			}
			if e.To != "" && (!slices.Contains(tl.Lanes, e.To) || e.To == e.Lane) {
				return fmt.Errorf("timeline: to %q must be another of %q", e.To, tl.Lanes)
			}
			if !oneOf(e.Mark, "", "ok", "bad", "note") {
				return fmt.Errorf("timeline: unknown mark %q (use ok, bad or note)", e.Mark)
			}
		}
	case b.Files != nil:
		for _, f := range b.Files.Roles {
			if !oneOf(f.Role, "core", "mechanical", "test", "config", "docs") {
				return fmt.Errorf("files: unknown role %q for %s (use core, mechanical, test, config or docs)", f.Role, f.File)
			}
		}
	}
	return nil
}

// InsertAfter puts steps right after the index-th step (counting across chapters), in the same chapter.
func (t *Tour) InsertAfter(index int, steps []Step) {
	n := 0
	for ci := range t.Chapters {
		c := &t.Chapters[ci]
		if index < n+len(c.Steps) {
			at := index - n + 1
			c.Steps = append(c.Steps[:at], append(append([]Step{}, steps...), c.Steps[at:]...)...)
			return
		}
		n += len(c.Steps)
	}
}
