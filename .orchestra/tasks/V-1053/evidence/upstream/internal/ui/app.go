package ui

import (
	"context"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"

	"github.com/init-co-jp/diff-tour/internal/generate"
	"github.com/init-co-jp/diff-tour/internal/git"
	"github.com/init-co-jp/diff-tour/internal/i18n"
	"github.com/init-co-jp/diff-tour/internal/render"
	"github.com/init-co-jp/diff-tour/internal/text"
	"github.com/init-co-jp/diff-tour/internal/tour"
)

// Target is a change that can be turned into a tour.
type Target struct {
	Base, Head string
	Label      string
	Current    bool
	Commits    int
	Committed  int64
	Cached     bool
	Key        string
	// Uncommitted means head is the working tree (including uncommitted changes).
	Uncommitted bool
}

// FindTargets returns the local branches that are ahead of the branch being compared against, with the current branch first.
func FindTargets(repo *git.Repo, base string, lang i18n.Lang, backend string) []Target {
	current := repo.CurrentBranch()
	var targets []Target
	// If there are uncommitted changes, put a target that includes them first and select it (changes just written by an AI are usually not committed yet).
	if repo.Dirty() {
		label := render.RefName(repo, git.Worktree)
		key := generate.CacheKey(repo, base, git.Worktree, lang, backend)
		cached, _ := generate.LoadCached(key)
		targets = append(targets, Target{Base: base, Head: git.Worktree, Label: label, Current: true,
			Commits: repo.Ahead(base, "HEAD"), Committed: time.Now().Unix(), Cached: cached != nil, Key: key, Uncommitted: true})
	}
	for _, b := range repo.Branches() {
		if b.Name == base || "origin/"+b.Name == base {
			continue
		}
		n := repo.Ahead(base, b.Name)
		if n == 0 {
			continue
		}
		key := generate.CacheKey(repo, base, b.Name, lang, backend)
		cached, _ := generate.LoadCached(key)
		t := Target{Base: base, Head: b.Name, Label: b.Name, Current: b.Name == current, Commits: n, Committed: b.Committed, Cached: cached != nil, Key: key}
		// The current branch comes first, right after the uncommitted target if there is one
		if t.Current {
			i := 0
			if len(targets) > 0 && targets[0].Uncommitted {
				i = 1
			}
			targets = append(targets[:i], append([]Target{t}, targets[i:]...)...)
		} else {
			targets = append(targets, t)
		}
	}
	return targets
}

func relativeTime(unix int64) string {
	d := time.Since(time.Unix(unix, 0))
	switch {
	case d < time.Minute:
		return i18n.T("time.now")
	case d < time.Hour:
		return i18n.T("time.minutes", int(d.Minutes()))
	case d < 24*time.Hour:
		return i18n.T("time.hours", int(d.Hours()))
	default:
		return i18n.T("time.days", int(d.Hours()/24))
	}
}

type screen int

const (
	screenPicker screen = iota
	screenGenerating
	screenViewer
	screenFailed
)

type progressMsg generate.Progress

type doneMsg struct {
	tour  *tour.Tour
	stats generate.Stats
	err   error
}

type tickMsg time.Time

// App runs pick a change -> generate the tour (or load it if saved) -> play it, all within a single screen.
type App struct {
	repo     *git.Repo
	lang     i18n.Lang
	backend  generate.Backend
	baseName string

	screen  screen
	targets []Target
	sel     int

	target   Target
	started  time.Time
	phase    string
	repair   int
	events   []generate.Event
	reads    int
	progress chan tea.Msg
	cancel   context.CancelFunc
	failure  string

	viewer *Viewer
	width  int
	height int
}

// NewPicker starts from the screen for picking a change.
func NewPicker(repo *git.Repo, base string, lang i18n.Lang, backend generate.Backend) *App {
	return &App{repo: repo, lang: lang, backend: backend, baseName: base, targets: FindTargets(repo, base, lang, backend.Name())}
}

// NewGenerating starts from the tour generation screen, for when the change is already decided.
func NewGenerating(repo *git.Repo, base, head string, lang i18n.Lang, backend generate.Backend) *App {
	a := &App{repo: repo, lang: lang, backend: backend, baseName: base}
	key := generate.CacheKey(repo, base, head, lang, backend.Name())
	a.target = Target{Base: base, Head: head, Label: render.RefName(repo, head), Key: key}
	a.screen = screenGenerating
	return a
}

func (a *App) Init() tea.Cmd {
	if a.screen == screenGenerating {
		return a.start(a.target)
	}
	return nil
}

func waitFor(ch chan tea.Msg) tea.Cmd {
	return func() tea.Msg { return <-ch }
}

func tick() tea.Cmd {
	return tea.Tick(time.Second, func(t time.Time) tea.Msg { return tickMsg(t) })
}

// start opens the saved tour if there is one; otherwise it starts generating one in a separate goroutine.
func (a *App) start(t Target) tea.Cmd {
	a.target = t
	if cached, err := generate.LoadCached(t.Key); err == nil && cached != nil {
		a.openViewer(cached, "")
		return nil
	}
	a.screen, a.started, a.phase = screenGenerating, time.Now(), "reading"
	a.events, a.reads, a.repair = nil, 0, 0
	ctx, cancel := context.WithCancel(context.Background())
	a.cancel = cancel
	ch := make(chan tea.Msg, 64)
	a.progress = ch
	work, err := generate.WorkDir(t.Key)
	if err != nil {
		a.fail(err)
		return nil
	}
	req := generate.Request{Repo: a.repo, Base: t.Base, Head: t.Head, Lang: a.lang}
	go func() {
		tr, stats, err := generate.Generate(ctx, a.backend, req, work, func(p generate.Progress) {
			select {
			case ch <- progressMsg(p):
			default: // if the screen can't keep up, dropping intermediate events is fine
			}
		})
		if err == nil {
			err = generate.SaveCached(t.Key, tr)
		}
		ch <- doneMsg{tr, stats, err}
	}()
	return tea.Batch(waitFor(ch), tick())
}

func (a *App) openViewer(t *tour.Tour, message string) {
	key := a.target.Key
	var asker *Asker
	if work, err := generate.WorkDir(key + "-ask"); err == nil {
		asker = &Asker{
			Backend: a.backend,
			Req:     generate.Request{Repo: a.repo, Base: t.Base, Head: t.Head, Lang: a.lang},
			WorkDir: work,
			Save:    func(t *tour.Tour) error { return generate.SaveCached(key, t) },
		}
	}
	a.viewer = NewViewer(render.Ctx{Tour: t, Repo: a.repo}, asker)
	a.viewer.width, a.viewer.height, a.viewer.message = a.width, a.height, message
	a.screen = screenViewer
}

func (a *App) fail(err error) {
	a.screen = screenFailed
	a.failure = err.Error()
}

func (a *App) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if size, ok := msg.(tea.WindowSizeMsg); ok {
		a.width, a.height = size.Width, size.Height
	}
	if a.screen == screenViewer {
		return a.viewer.Update(msg)
	}
	switch msg := msg.(type) {
	case progressMsg:
		a.phase, a.repair = msg.Phase, msg.Repair
		if msg.Event != nil {
			a.events = append(a.events, *msg.Event)
			if msg.Event.Kind == "read" {
				a.reads++
			}
		}
		return a, waitFor(a.progress)
	case doneMsg:
		if msg.err != nil {
			a.fail(msg.err)
			return a, nil
		}
		a.openViewer(msg.tour, i18n.T("gen.saved", msg.stats.CostUSD))
		return a, nil
	case tickMsg:
		if a.screen == screenGenerating {
			return a, tick()
		}
	case tea.KeyPressMsg:
		switch a.screen {
		case screenPicker:
			switch msg.String() {
			case "up", "k":
				a.sel = max(0, a.sel-1)
			case "down", "j":
				a.sel = min(len(a.targets)-1, a.sel+1)
			case "enter", "right", "space":
				if len(a.targets) > 0 {
					return a, a.start(a.targets[a.sel])
				}
			case "q", "ctrl+c":
				return a, tea.Quit
			}
		case screenGenerating:
			if s := msg.String(); s == "q" || s == "ctrl+c" {
				if a.cancel != nil {
					a.cancel()
				}
				return a, tea.Quit
			}
		case screenFailed:
			if s := msg.String(); s == "q" || s == "ctrl+c" || s == "enter" {
				return a, tea.Quit
			}
		}
	}
	return a, nil
}

func (a *App) View() tea.View {
	if a.screen == screenViewer {
		return a.viewer.View()
	}
	width := a.width
	if width == 0 {
		width = 80
	}
	inner := width - 2
	var lines []text.Line
	add := func(l text.Line) { lines = append(lines, text.Concat(text.Line{{Text: " "}}, text.Fit(l, inner, ""))) }
	header := func(title string) {
		add(nil)
		add(text.Line{{Text: " tour ", Style: "30;46"}, {Text: "  " + title, Style: "1"}})
		add(nil)
	}

	switch a.screen {
	case screenPicker:
		header(i18n.T("picker.title"))
		if len(a.targets) == 0 {
			add(text.Line{{Text: "   " + i18n.T("picker.empty", a.baseName), Style: "33"}})
		}
		nameW := 0
		for _, t := range a.targets {
			nameW = max(nameW, text.Width(t.Label))
		}
		for i, t := range a.targets {
			cursor, style := "   ", ""
			if i == a.sel {
				cursor, style = " ▸ ", "1;36"
			}
			var notes []string
			if t.Current {
				notes = append(notes, i18n.T("picker.current"))
			}
			if t.Uncommitted {
				if t.Commits > 0 {
					notes = append(notes, i18n.T("picker.commits", t.Commits))
				}
				notes = append(notes, i18n.T("picker.uncommittedNote"))
			} else {
				notes = append(notes, i18n.T("picker.commits", t.Commits), relativeTime(t.Committed))
			}
			l := text.Line{{Text: cursor, Style: "36"}, {Text: t.Label + strings.Repeat(" ", nameW-text.Width(t.Label)), Style: style}, {Text: "   " + strings.Join(notes, " · "), Style: "90"}}
			if t.Cached {
				l = append(l, text.Span{Text: " · " + i18n.T("picker.cached"), Style: "32"})
			}
			add(l)
		}
		add(text.Line{{Text: "   ────────────────", Style: "90"}})
		add(text.Line{{Text: "   " + i18n.T("picker.advanced"), Style: "90"}})
		add(nil)
		add(text.Line{{Text: " " + i18n.T("picker.info", a.baseName, a.backend.Name()), Style: "90"}})
		add(text.Line{{Text: " " + i18n.T("picker.keys"), Style: "90"}})

	case screenGenerating:
		header(i18n.T("gen.title", a.target.Label, a.target.Base))
		elapsed := time.Since(a.started).Round(time.Second)
		status := i18n.T("gen.reading", a.backend.Name(), elapsed)
		if a.phase == "repairing" {
			status = i18n.T("gen.repairing", a.repair, generate.MaxRepairs, elapsed)
		}
		add(text.Line{{Text: " " + spinner(elapsed) + " ", Style: "36"}, {Text: status}})
		add(nil)
		add(text.Line{{Text: "   " + i18n.T("gen.files", a.reads), Style: "90"}})
		show := a.events
		room := max(3, a.height-14)
		if len(show) > room {
			show = show[len(show)-room:]
		}
		for _, e := range show {
			if e.Kind == "read" {
				add(text.Line{{Text: "   " + e.Detail}})
			} else {
				add(text.Line{{Text: "   " + i18n.T("gen.search", e.Detail), Style: "90"}})
			}
		}
		add(nil)
		add(text.Line{{Text: " " + i18n.T("gen.note"), Style: "90"}})
		add(text.Line{{Text: " " + i18n.T("gen.keys"), Style: "90"}})

	case screenFailed:
		header(i18n.T("gen.failed"))
		for _, l := range text.Wrap([]text.Span{{Text: a.failure, Style: "91"}}, inner-2) {
			add(text.Concat(text.Line{{Text: "  "}}, l))
		}
		add(nil)
		add(text.Line{{Text: " " + i18n.T("gen.failKeys"), Style: "90"}})
	}

	view := tea.NewView(join(lines, false))
	view.AltScreen = true
	return view
}

func spinner(d time.Duration) string {
	frames := []string{"◐", "◓", "◑", "◒"}
	return frames[int(d.Seconds())%len(frames)]
}
