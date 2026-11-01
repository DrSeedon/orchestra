package render

import (
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/init-co-jp/diff-tour/internal/git"
	"github.com/init-co-jp/diff-tour/internal/highlight"
	"github.com/init-co-jp/diff-tour/internal/i18n"
	"github.com/init-co-jp/diff-tour/internal/schema"
	"github.com/init-co-jp/diff-tour/internal/text"
	"github.com/init-co-jp/diff-tour/internal/tour"
)

// Ctx holds what rendering needs.
type Ctx struct {
	Tour *tour.Tour
	Repo *git.Repo
	// CanAsk shows the key for asking a question.
	CanAsk bool
}

// Ref turns "base" / "head" into the commit to read.
// "base" is not the tip of Tour.Base but its merge base with head. The diff is also taken against the merge base, so this matches it.
// That way the pre-change code is shown correctly even if the base branch has moved on since the branch point.
func (c Ctx) Ref(at string) string {
	if at == "base" {
		return c.Repo.MergeBase(c.Tour.Base, c.Tour.Head)
	}
	return c.Tour.Head
}

func errorLines(msg string, width int) []text.Line {
	return text.Wrap([]text.Span{{Text: "⚠ " + msg, Style: "91"}}, width)
}

func fileHeader(file, detail, note string, width int) text.Line {
	l := text.Line{{Text: " " + file + " ", Style: "1;97;100"}, {Text: " " + detail, Style: "90"}}
	if note != "" {
		l = append(l, text.Span{Text: "  " + note, Style: "33"})
	}
	return text.Fit(l, width, "")
}

func dim(l text.Line) text.Line {
	return l.Map(func(s string) string { return text.Join("2", s) })
}

func renderCode(ref *tour.CodeRef, width int, ctx Ctx) []text.Line {
	at := ctx.Ref(ref.At)
	src := ctx.Repo.Show(at, ref.File)
	if src == nil {
		return errorLines(i18n.T("err.fileNotFound", ref.File, at), width)
	}
	hl0, hl1 := ref.Lines[0], ref.Lines[1]
	if hl0 < 1 || hl1 > len(src) || hl0 > hl1 {
		return errorLines(i18n.T("err.lineRange", ref.File, hl0, hl1, len(src)), width)
	}
	s0, s1 := max(1, hl0-2), min(len(src), hl1+2)
	if ref.Show != nil {
		s0, s1 = max(1, ref.Show[0]), min(len(src), ref.Show[1])
	}
	colored := highlight.Lines(ref.File, "", src)
	numW := len(strconv.Itoa(s1))
	detail := fmt.Sprintf("L%d–%d", hl0, hl1)
	if hl0 == hl1 {
		detail = fmt.Sprintf("L%d", hl0)
	}
	out := []text.Line{fileHeader(ref.File, detail, ref.Note, width)}
	for n := s0; n <= s1; n++ {
		on := n >= hl0 && n <= hl1
		numStyle, mark := "90", "  "
		code := dim(colored[n-1])
		if on {
			numStyle, mark, code = "33", "▌ ", colored[n-1]
		}
		gutter := text.Line{{Text: fmt.Sprintf("%*d ", numW, n), Style: numStyle}, {Text: mark, Style: "33"}}
		out = append(out, wrapCode(gutter, code, width, "")...)
		// Notes attached to this line go right under it, pointing up at it
		for _, m := range ref.Marks {
			if m.Line != n {
				continue
			}
			indent := numW + 3
			for k, l := range text.Wrap(text.ParseInline(m.Text, "93"), max(8, width-indent-3)) {
				lead := "╰▶ "
				if k > 0 {
					lead = "   "
				}
				out = append(out, text.Concat(text.Line{{Text: strings.Repeat(" ", indent)}, {Text: lead, Style: "93"}}, l))
			}
		}
	}
	return out
}

func pickHunks(ctx Ctx, ref *tour.DiffRef) ([]git.Hunk, string) {
	hunks, ok := ctx.Repo.Diff(ctx.Tour.Base, ctx.Tour.Head, ref.File)
	if !ok || len(hunks) == 0 {
		return nil, i18n.T("err.noDiff", ref.File)
	}
	if ref.Hunks == nil {
		return hunks, ""
	}
	var picked []git.Hunk
	for _, i := range ref.Hunks {
		if i < 0 || i >= len(hunks) {
			return nil, i18n.T("err.noHunk", ref.File, ref.Hunks)
		}
		picked = append(picked, hunks[i])
	}
	return picked, ""
}

func renderDiff(ref *tour.DiffRef, width int, ctx Ctx) []text.Line {
	picked, errMsg := pickHunks(ctx, ref)
	if errMsg != "" {
		return errorLines(errMsg, width)
	}
	added, removed, numW := 0, 0, 1
	for _, h := range picked {
		for _, l := range h.Lines {
			switch l.Kind {
			case '+':
				added++
			case '-':
				removed++
			}
			numW = max(numW, len(strconv.Itoa(max(l.OldNo, l.NewNo))))
		}
	}
	out := []text.Line{fileHeader(ref.File, i18n.T("diff.summary", added, removed), "", width)}
	for hi, h := range picked {
		if hi > 0 {
			out = append(out, text.Line{{Text: "⋯", Style: "90"}})
		}
		src := make([]string, len(h.Lines))
		for i, l := range h.Lines {
			src[i] = l.Text
		}
		colored := highlight.Lines(ref.File, "", src)
		for i, l := range h.Lines {
			var bg, sign, signStyle string
			num := l.NewNo
			switch l.Kind {
			case '+':
				bg, sign, signStyle = "48;5;22", "+ ", "92"
			case '-':
				bg, sign, signStyle, num = "48;5;52", "− ", "91", l.OldNo
			default:
				sign = "  "
			}
			gutter := text.Line{
				{Text: fmt.Sprintf("%*d ", numW, num), Style: text.Join(bg, "90")},
				{Text: sign, Style: text.Join(bg, signStyle)},
			}
			code := colored[i].Map(func(s string) string {
				if l.Kind == ' ' {
					return text.Join(bg, "2", s)
				}
				return text.Join(bg, s)
			})
			out = append(out, wrapCode(gutter, code, width, bg)...)
		}
	}
	return out
}

func renderSnippet(s *tour.Snippet, width int) []text.Line {
	out := []text.Line{text.Fit(text.Line{{Text: " " + i18n.T("tag.example") + " ", Style: "30;43"}, {Text: " " + s.Label, Style: "33"}}, width, "")}
	for _, code := range highlight.Lines("", s.Lang, strings.Split(s.Text, "\n")) {
		out = append(out, text.Fit(text.Concat(text.Line{{Text: "┆ ", Style: "33"}}, code), width, ""))
	}
	return out
}

var preMarks = map[rune]string{'✔': "92", '✘': "91", '★': "93", '✎': "33"}

func renderPre(s string, width int) []text.Line {
	var out []text.Line
	for _, src := range strings.Split(s, "\n") {
		var l text.Line
		for _, r := range src {
			l = text.Append(l, string(r), preMarks[r])
		}
		out = append(out, text.Fit(l, width, ""))
	}
	return out
}

func plainWidth(s string) int {
	return text.Width(strings.NewReplacer("**", "", "`", "").Replace(s))
}

// columnWidths decides the column widths. If they don't fit, it shrinks the widest column first.
func columnWidths(head []string, rows [][]string, avail int) []int {
	widths := make([]int, len(head))
	for i, h := range head {
		widths[i] = plainWidth(h)
		for _, r := range rows {
			if i < len(r) {
				widths[i] = max(widths[i], plainWidth(r[i]))
			}
		}
	}
	for sum(widths) > avail {
		i := argmax(widths)
		if widths[i] <= 6 {
			break
		}
		widths[i]--
	}
	return widths
}

func renderTable(t *tour.Table, width int) []text.Line {
	const gap = 2
	n := len(t.Head)
	widths := columnWidths(t.Head, t.Rows, width-gap*(n-1))
	row := func(cells []string, style string) []text.Line {
		wrapped := make([][]text.Line, n)
		h := 0
		for i := range n {
			cell := ""
			if i < len(cells) {
				cell = cells[i]
			}
			wrapped[i] = text.Wrap(text.ParseInline(cell, style), widths[i])
			h = max(h, len(wrapped[i]))
		}
		var out []text.Line
		for k := range h {
			var l text.Line
			for i := range n {
				var cell text.Line
				if k < len(wrapped[i]) {
					cell = wrapped[i][k]
				}
				l = text.Concat(l, text.Fit(cell, widths[i], ""))
				if i < n-1 {
					l = text.Append(l, strings.Repeat(" ", gap), "")
				}
			}
			out = append(out, l)
		}
		return out
	}
	ruleW := min(width, sum(widths)+gap*(n-1))
	out := append(row(t.Head, "1"), text.Line{{Text: strings.Repeat("─", ruleW), Style: "90"}})
	for i, r := range t.Rows {
		if i > 0 {
			out = append(out, text.Line{{Text: strings.Repeat("┄", ruleW), Style: "90"}})
		}
		out = append(out, row(r, "")...)
	}
	return out
}

type boxRow struct {
	cells  []string
	styles []string
	marker text.Span
}

// boxTable is a table framed with box-drawing lines. It is used to show database tables and rows.
func boxTable(head []string, headStyles []string, rows []boxRow, width int) []text.Line {
	n := len(head)
	cells := make([][]string, len(rows))
	for i, r := range rows {
		cells[i] = r.cells
	}
	widths := columnWidths(head, cells, width-2-(n+1)-2*n)
	const border = "90"
	rule := func(l, m, r string) text.Line {
		parts := make([]string, n)
		for i, w := range widths {
			parts[i] = strings.Repeat("─", w+2)
		}
		return text.Line{{Text: "  "}, {Text: l + strings.Join(parts, m) + r, Style: border}}
	}
	line := func(cells, styles []string, marker text.Span) []text.Line {
		wrapped := make([][]text.Line, n)
		h := 0
		for i := range n {
			cell, style := "", ""
			if i < len(cells) {
				cell = cells[i]
			}
			if i < len(styles) {
				style = styles[i]
			}
			wrapped[i] = text.Wrap(text.ParseInline(cell, style), widths[i])
			h = max(h, len(wrapped[i]))
		}
		var out []text.Line
		for k := range h {
			l := text.Line{{Text: "  "}}
			if k == 0 && marker.Text != "" {
				l = text.Line{marker}
			}
			l = append(l, text.Span{Text: "│", Style: border})
			for i := range n {
				var cell text.Line
				if k < len(wrapped[i]) {
					cell = wrapped[i][k]
				}
				l = text.Concat(l, text.Line{{Text: " "}}, text.Fit(cell, widths[i], ""), text.Line{{Text: " "}, {Text: "│", Style: border}})
			}
			out = append(out, l)
		}
		return out
	}
	bold := make([]string, n)
	for i := range n {
		s := ""
		if i < len(headStyles) {
			s = headStyles[i]
		}
		bold[i] = text.Join("1", s)
	}
	out := []text.Line{rule("┌", "┬", "┐")}
	out = append(out, line(head, bold, text.Span{})...)
	out = append(out, rule("├", "┼", "┤"))
	for _, r := range rows {
		out = append(out, line(r.cells, r.styles, r.marker)...)
	}
	return append(out, rule("└", "┴", "┘"))
}

type changeStyle struct{ label, style, marker string }

func changeOf(c schema.Change) changeStyle {
	switch c {
	case schema.Added:
		return changeStyle{i18n.T("change.added"), "92", "+ "}
	case schema.Removed:
		return changeStyle{i18n.T("change.removed"), "91", "− "}
	case schema.Changed:
		return changeStyle{i18n.T("change.changed"), "93", "~ "}
	default:
		return changeStyle{i18n.T("change.same"), "90", "  "}
	}
}

func schemaError(err error, width int) []text.Line {
	var unsafe *schema.UnsafeError
	var mig *schema.MigrationError
	switch {
	case errors.As(err, &unsafe):
		return errorLines(i18n.T("err.unsafeSQL", unsafe.File), width)
	case errors.As(err, &mig):
		return errorLines(i18n.T("err.migration", mig.File, mig.Err), width)
	default:
		return errorLines(i18n.T("err.schema", err), width)
	}
}

func renderSchema(ref *tour.SchemaRef, width int, ctx Ctx) []text.Line {
	before, err := schema.Load(ctx.Repo, ctx.Ref("base"), ref.Migrations)
	if err != nil {
		return schemaError(err, width)
	}
	after, err := schema.Load(ctx.Repo, ctx.Tour.Head, ref.Migrations)
	if err != nil {
		return schemaError(err, width)
	}
	names := ref.Tables
	if names == nil {
		seen := map[string]bool{}
		for n := range before {
			seen[n] = true
		}
		for n := range after {
			seen[n] = true
		}
		for n := range seen {
			if schema.DiffTable(before[n], after[n]).Change != schema.Same {
				names = append(names, n)
			}
		}
		sort.Strings(names)
	}
	focus := map[string]bool{}
	for _, f := range ref.Focus {
		focus[f] = true
	}
	out := []text.Line{text.Fit(text.Line{
		{Text: " " + i18n.T("schema.title") + " ", Style: "1;97;100"},
		{Text: "  " + i18n.T("schema.desc", ref.Migrations, ctx.Tour.Base, RefName(ctx.Repo, ctx.Tour.Head)), Style: "90"},
	}, width, "")}
	for _, name := range names {
		if before[name] == nil && after[name] == nil {
			out = append(out, errorLines(i18n.T("err.noTable", name), width)...)
			continue
		}
		d := schema.DiffTable(before[name], after[name])
		c := changeOf(d.Change)
		label := c.label
		if d.Change == schema.Added {
			label = i18n.T("schema.newTable")
		}
		out = append(out, nil, text.Line{{Text: "  " + name, Style: "1"}, {Text: "  " + label, Style: c.style}})
		var rows []boxRow
		for _, col := range d.Columns {
			cc := changeOf(col.Change)
			style := ""
			if col.Change != schema.Same {
				style = cc.style
			}
			marker := text.Span{Text: cc.marker, Style: cc.style}
			if focus[name+"."+col.Name] {
				style, marker = text.Join("1", style), text.Span{Text: "▶ ", Style: "1;33"}
			}
			constraints := col.Constraints
			if constraints == "" {
				constraints = "—"
			}
			rows = append(rows, boxRow{cells: []string{col.Name, col.Type, constraints}, styles: []string{style, style, style}, marker: marker})
		}
		out = append(out, boxTable([]string{i18n.T("schema.column"), i18n.T("schema.type"), i18n.T("schema.constraints")}, nil, rows, width)...)
		for _, idx := range d.Indexes {
			ic := changeOf(idx.Change)
			kind := i18n.T("schema.index")
			if idx.Unique {
				kind = i18n.T("schema.unique")
			}
			style := ""
			if idx.Change != schema.Same {
				style = ic.style
			}
			out = append(out, text.Line{
				{Text: ic.marker, Style: ic.style},
				{Text: kind + " ", Style: "90"},
				{Text: fmt.Sprintf("%s (%s)", idx.Name, strings.Join(idx.Columns, ", ")), Style: style},
			})
		}
	}
	return out
}

func renderRows(r *tour.Rows, width int) []text.Line {
	added := map[string]bool{}
	for _, a := range r.Added {
		added[a] = true
	}
	styles := make([]string, len(r.Head))
	for i, h := range r.Head {
		if added[h] {
			styles[i] = "92"
		}
	}
	tag := r.Tag
	if tag == "" {
		tag = i18n.T("tag.example")
	}
	out := []text.Line{text.Fit(text.Line{{Text: " " + tag + " ", Style: "30;43"}, {Text: " " + r.Label, Style: "33"}}, width, "")}
	rows := make([]boxRow, len(r.Data))
	for i, d := range r.Data {
		rows[i] = boxRow{cells: d, styles: styles}
	}
	out = append(out, boxTable(r.Head, styles, rows, width)...)
	if len(added) > 0 {
		out = append(out, text.Line{{Text: "  " + i18n.T("rows.added"), Style: "92"}})
	}
	return out
}

// RefName is the ref name shown on screen. The working tree is written as "branch name + uncommitted changes".
func RefName(repo *git.Repo, ref string) string {
	if ref != git.Worktree {
		return ref
	}
	if branch := repo.CurrentBranch(); branch != "" {
		return branch + " + " + i18n.T("picker.uncommitted")
	}
	return i18n.T("picker.uncommitted")
}

func renderTarget(width int, ctx Ctx) []text.Line {
	stat := ctx.Repo.Shortstat(ctx.Tour.Base, ctx.Tour.Head)
	commits := ctx.Repo.Commits(ctx.Tour.Base, ctx.Tour.Head)
	out := []text.Line{
		{{Text: RefName(ctx.Repo, ctx.Tour.Head), Style: "1;36"}, {Text: i18n.T("target.branched", ctx.Tour.Base), Style: "90"}},
		{{Text: i18n.T("target.summary", len(commits), stat.Files, stat.Insertions, stat.Deletions)}},
		nil,
	}
	for _, c := range commits {
		out = append(out, text.Wrap([]text.Span{{Text: c.Hash, Style: "33"}, {Text: " " + c.Subject}}, width)...)
	}
	return out
}

func basisLabel(b tour.Basis) (string, string) {
	switch b {
	case tour.Fact:
		return i18n.T("basis.fact"), "30;42"
	case tour.Inferred:
		return i18n.T("basis.inferred"), "30;104"
	default:
		return i18n.T("basis.opinion"), "30;43"
	}
}

// Block renders a single block at width width.
func Block(b tour.Block, width int, ctx Ctx) []text.Line {
	switch {
	case b.P != nil:
		spans := text.ParseInline(*b.P, "")
		if b.Basis != "" {
			label, style := basisLabel(b.Basis)
			spans = append([]text.Span{{Text: " " + label + " ", Style: style}, {Text: " "}}, spans...)
		}
		return text.Wrap(spans, width)
	case b.Quote != nil:
		var out []text.Line
		for _, para := range strings.Split(*b.Quote, "\n") {
			for _, l := range text.Wrap(text.ParseInline(para, ""), width-2) {
				out = append(out, text.Concat(text.Line{{Text: "┃ ", Style: "36"}}, l))
			}
		}
		return out
	case b.List != nil:
		var out []text.Line
		for _, item := range b.List {
			for i, l := range text.Wrap(text.ParseInline(item, ""), width-2) {
				bullet := "  "
				if i == 0 {
					bullet = "・"
				}
				out = append(out, text.Concat(text.Line{{Text: bullet, Style: "36"}}, l))
			}
		}
		return out
	case b.Pre != nil:
		return renderPre(*b.Pre, width)
	case b.Table != nil:
		return renderTable(b.Table, width)
	case b.Code != nil:
		return renderCode(b.Code, width, ctx)
	case b.Diff != nil:
		return renderDiff(b.Diff, width, ctx)
	case b.Snippet != nil:
		return renderSnippet(b.Snippet, width)
	case b.Schema != nil:
		return renderSchema(b.Schema, width, ctx)
	case b.Rows != nil:
		return renderRows(b.Rows, width)
	case b.Flow != nil:
		return renderFlow(b.Flow, width)
	case b.Timeline != nil:
		return renderTimeline(b.Timeline, width)
	case b.Files != nil:
		return renderFiles(b.Files, width, ctx)
	case b.Target:
		return renderTarget(width, ctx)
	}
	return nil
}

func sum(xs []int) int {
	s := 0
	for _, x := range xs {
		s += x
	}
	return s
}

func argmax(xs []int) int {
	best := 0
	for i, x := range xs {
		if x > xs[best] {
			best = i
		}
	}
	return best
}

// wrapCode lays out one line of code after its gutter. A line too long for the width continues on
// the next lines under a ↪ mark instead of being cut off, so comments and long expressions stay readable.
func wrapCode(gutter, code text.Line, width int, bg string) []text.Line {
	room := width - gutter.Width()
	if room < 12 || text.TrimRight(code).Width() <= room {
		return []text.Line{text.Fit(text.Concat(gutter, code), width, bg)}
	}
	cont := text.Line{{Text: strings.Repeat(" ", gutter.Width()-2), Style: bg}, {Text: "↪ ", Style: text.Join(bg, "90")}}
	var out []text.Line
	rest := text.TrimRight(code)
	for first := true; rest.Width() > 0; first = false {
		g := cont
		if first {
			g = gutter
		}
		piece := cutRight(rest, breakAt(rest, room))
		out = append(out, text.Fit(text.Concat(g, piece), width, bg))
		rest = cutLeft(rest, piece.Width())
	}
	return out
}

// breakAt is how many columns of l go on one line of the given room: up to the last space that fits,
// so words aren't split, unless that would leave the line less than half full.
func breakAt(l text.Line, room int) int {
	if l.Width() <= room {
		return room
	}
	col, last := 0, 0
	for _, s := range l {
		for _, r := range s.Text {
			w := text.RuneWidth(r)
			if col+w > room {
				if last >= room/2 {
					return last
				}
				return room
			}
			col += w
			if r == ' ' {
				last = col
			}
		}
	}
	return room
}
