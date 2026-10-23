// Package ui provides the terminal screens (tour playback and initial setup).
package ui

import (
	"strconv"
	"strings"

	tea "charm.land/bubbletea/v2"

	"github.com/init-co-jp/diff-tour/internal/i18n"
	"github.com/init-co-jp/diff-tour/internal/render"
	"github.com/init-co-jp/diff-tour/internal/text"
	"github.com/init-co-jp/diff-tour/internal/tour"
)

type editorDoneMsg struct {
	err    error
	copied bool
	ref    string
}

// Viewer plays a tour one step at a time.
type Viewer struct {
	ctx       render.Ctx
	steps     []tour.FlatStep
	index     int
	scroll    int
	maxScroll int
	width     int
	height    int
	message   string
	asker     *Asker
	ask       askState
}

// NewViewer plays a tour. With an asker, the reader can ask questions with `?`.
func NewViewer(ctx render.Ctx, asker *Asker) *Viewer {
	ctx.CanAsk = asker != nil
	return &Viewer{ctx: ctx, steps: ctx.Tour.Steps(), asker: asker}
}

func (v *Viewer) Init() tea.Cmd { return nil }

func (v *Viewer) goTo(i int) {
	if i < 0 || i >= len(v.steps) || i == v.index {
		return
	}
	v.index, v.scroll = i, 0
}

func (v *Viewer) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg.(type) {
	case answerProgressMsg, answerDoneMsg, answerTickMsg:
		return v.updateAsk(msg)
	case tea.KeyPressMsg, tea.PasteMsg:
		if v.ask.mode != askOff {
			return v.updateAsk(msg)
		}
	}
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		v.width, v.height = msg.Width, msg.Height
	case editorDoneMsg:
		switch {
		case msg.err != nil:
			v.message = i18n.T("editor.fail", msg.err)
		case msg.copied:
			v.message = i18n.T("editor.copy", msg.ref)
		}
	case tea.KeyPressMsg:
		v.message = ""
		switch msg.String() {
		case "right", "l", "space", "enter", "n":
			v.goTo(v.index + 1)
		case "left", "h", "backspace", "p":
			v.goTo(v.index - 1)
		case "down", "j":
			v.scroll = min(v.scroll+1, v.maxScroll)
		case "up", "k":
			v.scroll = max(v.scroll-1, 0)
		case "o":
			return v, v.openEditor()
		case "?", "/":
			v.openAsk()
		case "q", "ctrl+c":
			return v, tea.Quit
		}
	}
	return v, nil
}

func (v *Viewer) openEditor() tea.Cmd {
	loc := render.Location(v.steps[v.index], v.ctx)
	if loc == nil {
		return nil
	}
	ref := v.ctx.Ref(loc.At)
	path, copied, err := PrepareFile(v.ctx.Repo, ref, loc.File)
	if err != nil {
		v.message = i18n.T("editor.fail", err)
		return nil
	}
	return tea.ExecProcess(editorCmd(path, loc.Line), func(err error) tea.Msg {
		return editorDoneMsg{err: err, copied: copied, ref: ref}
	})
}

func (v *Viewer) View() tea.View {
	view := tea.NewView("")
	view.AltScreen = true
	if v.width == 0 || v.height == 0 {
		return view
	}
	lines, maxScroll := render.Frame(v.ctx, v.steps, v.index, v.scroll, v.width, v.height, v.message)
	if v.ask.mode != askOff {
		// The panel covers the bottom of the step, above the progress bar
		panel := v.askPanel(v.width)
		keep := max(2, len(lines)-2-len(panel))
		lines = append(append(lines[:keep:keep], panel...), lines[len(lines)-2:]...)
	}
	v.maxScroll = maxScroll
	v.scroll = min(v.scroll, maxScroll)
	view.SetContent(join(lines, false))
	return view
}

func join(lines []text.Line, plain bool) string {
	out := make([]string, len(lines))
	for i, l := range lines {
		out[i] = text.ANSI(l, plain)
	}
	return strings.Join(out, "\n")
}

// Dump renders every step at the given size and returns the result (for inspection).
func Dump(ctx render.Ctx, cols, rows int, plain bool) string {
	steps := ctx.Tour.Steps()
	var b strings.Builder
	for i := range steps {
		lines, overflow := render.Frame(ctx, steps, i, 0, cols, rows, "")
		b.WriteString("\n===== step ")
		b.WriteString(strconv.Itoa(i + 1))
		if overflow > 0 {
			b.WriteString("  (overflow " + strconv.Itoa(overflow) + " lines)")
		}
		b.WriteString(" =====\n")
		b.WriteString(join(lines, plain))
		b.WriteString("\n")
	}
	return b.String()
}
