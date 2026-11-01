// Package git collects the git operations tour uses.
// tour is read-only, so it only uses commands that modify neither the working tree nor .git.
package git

import (
	"io"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
)

type DiffLine struct {
	Kind  byte // ' ', '+', '-'
	OldNo int  // 0 means "not present on that side"
	NewNo int
	Text  string
}

type Hunk struct {
	Header string
	Lines  []DiffLine
}

type Commit struct {
	Hash    string
	Subject string
}

type Repo struct {
	Dir   string
	mu    sync.Mutex
	cache map[string]*string
}

func Open(dir string) *Repo {
	return &Repo{Dir: dir, cache: map[string]*string{}}
}

// run runs git and returns its stdout, or nil on failure.
func (r *Repo) run(args ...string) *string {
	key := strings.Join(args, "\x00")
	r.mu.Lock()
	if out, ok := r.cache[key]; ok {
		r.mu.Unlock()
		return out
	}
	r.mu.Unlock()

	cmd := exec.Command("git", append([]string{"-C", r.Dir, "--no-pager"}, args...)...)
	// Don't allow incidental writes such as lock files either.
	cmd.Env = append(os.Environ(), "GIT_OPTIONAL_LOCKS=0")
	var res *string
	if b, err := cmd.Output(); err == nil {
		s := string(b)
		res = &s
	}
	r.mu.Lock()
	r.cache[key] = res
	r.mu.Unlock()
	return res
}

// Show returns a file's contents at a given revision, line by line, or nil if it does not exist.
func (r *Repo) Show(ref, file string) []string {
	if ref == Worktree {
		return r.showWorktree(file)
	}
	out := r.run("show", ref+":"+file)
	if out == nil {
		return nil
	}
	return strings.Split(strings.TrimSuffix(*out, "\n"), "\n")
}

// Diff is the change in head since it branched from base (three-dot, i.e. compared against the fork point).
func (r *Repo) Diff(base, head, file string) ([]Hunk, bool) {
	if head == Worktree {
		return ParseDiff(r.worktreeDiff(base, file)), true
	}
	out := r.run("diff", "--no-color", "--no-ext-diff", "-U3", base+"..."+head, "--", file)
	if out == nil {
		return nil, false
	}
	return ParseDiff(*out), true
}

// MergeBase is the commit where a and b diverged. If none is found, it returns a unchanged.
func (r *Repo) MergeBase(a, b string) string {
	if b == Worktree {
		b = "HEAD"
	}
	if out := r.run("merge-base", a, b); out != nil {
		return strings.TrimSpace(*out)
	}
	return a
}

// ListFiles returns the paths of the files under dir at a given revision.
func (r *Repo) ListFiles(ref, dir string) []string {
	if ref == Worktree {
		prefix := strings.TrimSuffix(dir, "/") + "/"
		var files []string
		for f := range r.worktreeFiles() {
			if dir == "" || dir == "." || strings.HasPrefix(f, prefix) {
				files = append(files, f)
			}
		}
		return files
	}
	out := r.run("ls-tree", "-r", "--name-only", ref, "--", dir)
	if out == nil {
		return nil
	}
	return nonEmpty(strings.Split(*out, "\n"))
}

// Commits returns the commits in head but not in base, oldest first.
func (r *Repo) Commits(base, head string) []Commit {
	if head == Worktree {
		head = "HEAD"
	}
	out := r.run("log", "--reverse", "--format=%h%x09%s", base+".."+head)
	if out == nil {
		return nil
	}
	var commits []Commit
	for _, l := range nonEmpty(strings.Split(*out, "\n")) {
		hash, subject, _ := strings.Cut(l, "\t")
		commits = append(commits, Commit{hash, subject})
	}
	return commits
}

type Stat struct{ Files, Insertions, Deletions int }

var statRe = regexp.MustCompile(`(\d+) (file|insertion|deletion)`)

func (r *Repo) Shortstat(base, head string) Stat {
	if head == Worktree {
		return worktreeStat(r.worktreeDiff(base))
	}
	var s Stat
	out := r.run("diff", "--shortstat", base+"..."+head)
	if out == nil {
		return s
	}
	for _, m := range statRe.FindAllStringSubmatch(*out, -1) {
		n, _ := strconv.Atoi(m[1])
		switch m[2] {
		case "file":
			s.Files = n
		case "insertion":
			s.Insertions = n
		case "deletion":
			s.Deletions = n
		}
	}
	return s
}

var hunkRe = regexp.MustCompile(`^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)`)

func ParseDiff(s string) []Hunk {
	var hunks []Hunk
	var oldNo, newNo int
	for _, line := range strings.Split(s, "\n") {
		if m := hunkRe.FindStringSubmatch(line); m != nil {
			oldNo, _ = strconv.Atoi(m[1])
			newNo, _ = strconv.Atoi(m[2])
			hunks = append(hunks, Hunk{Header: strings.TrimSpace(m[3])})
			continue
		}
		if len(hunks) == 0 || line == "" {
			continue
		}
		h := &hunks[len(hunks)-1]
		switch line[0] {
		case '+':
			h.Lines = append(h.Lines, DiffLine{Kind: '+', NewNo: newNo, Text: line[1:]})
			newNo++
		case '-':
			h.Lines = append(h.Lines, DiffLine{Kind: '-', OldNo: oldNo, Text: line[1:]})
			oldNo++
		case ' ':
			h.Lines = append(h.Lines, DiffLine{Kind: ' ', OldNo: oldNo, NewNo: newNo, Text: line[1:]})
			oldNo++
			newNo++
		}
	}
	return hunks
}

func nonEmpty(ss []string) []string {
	out := ss[:0]
	for _, s := range ss {
		if s != "" {
			out = append(out, s)
		}
	}
	return out
}

// RevParse resolves a ref to a commit hash, or returns "" if it cannot be resolved.
func (r *Repo) RevParse(ref string) string {
	if ref == Worktree {
		return r.worktreeID()
	}
	out := r.run("rev-parse", "--verify", "--quiet", ref+"^{commit}")
	if out == nil {
		return ""
	}
	return strings.TrimSpace(*out)
}

// Resolve returns the name under which ref exists here: ref itself, or else a remote-tracking branch of the same name
// (a saved tour names its branches, and a fresh clone has them only as origin/<branch>). It returns "" if neither exists.
func (r *Repo) Resolve(ref string) string {
	if ref == Worktree || r.RevParse(ref) != "" {
		return ref
	}
	if r.RevParse("origin/"+ref) != "" {
		return "origin/" + ref
	}
	if out := r.run("for-each-ref", "--format=%(refname:short)", "refs/remotes/*/"+ref); out != nil {
		if name, _, _ := strings.Cut(strings.TrimSpace(*out), "\n"); name != "" {
			return name
		}
	}
	return ""
}

// CurrentBranch is the name of the current branch, or "" when not on a branch.
func (r *Repo) CurrentBranch() string {
	out := r.run("symbolic-ref", "--quiet", "--short", "HEAD")
	if out == nil {
		return ""
	}
	return strings.TrimSpace(*out)
}

// DefaultBranch is the branch to compare changes against: the one origin's HEAD points to, or else whichever of main, master, etc. exists.
func (r *Repo) DefaultBranch() string {
	if out := r.run("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"); out != nil {
		name := strings.TrimPrefix(strings.TrimSpace(*out), "origin/")
		if r.RevParse(name) != "" {
			return name
		}
		return "origin/" + name
	}
	for _, name := range []string{"main", "master", "trunk", "develop"} {
		if r.RevParse(name) != "" {
			return name
		}
	}
	return ""
}

type Branch struct {
	Name      string
	Committed int64 // time of the last commit (Unix seconds)
	Subject   string
}

// Branches returns the local branches, most recently committed first.
func (r *Repo) Branches() []Branch {
	out := r.run("for-each-ref", "--sort=-committerdate", "--format=%(refname:short)%09%(committerdate:unix)%09%(subject)", "refs/heads/")
	if out == nil {
		return nil
	}
	var branches []Branch
	for _, l := range nonEmpty(strings.Split(*out, "\n")) {
		parts := strings.SplitN(l, "\t", 3)
		if len(parts) < 3 {
			continue
		}
		ts, _ := strconv.ParseInt(parts[1], 10, 64)
		branches = append(branches, Branch{parts[0], ts, parts[2]})
	}
	return branches
}

// Ahead is the number of commits in head but not in base.
func (r *Repo) Ahead(base, head string) int {
	if head == Worktree {
		head = "HEAD"
	}
	out := r.run("rev-list", "--count", base+".."+head)
	if out == nil {
		return 0
	}
	n, _ := strconv.Atoi(strings.TrimSpace(*out))
	return n
}

// RawDiff returns the raw diff from base's fork point to head.
func (r *Repo) RawDiff(base, head string) string {
	if head == Worktree {
		return r.worktreeDiff(base)
	}
	out := r.run("diff", "--no-color", "--no-ext-diff", base+"..."+head)
	if out == nil {
		return ""
	}
	return *out
}

// CommitMessages returns the messages (with bodies) of the commits in head but not in base.
func (r *Repo) CommitMessages(base, head string) string {
	if head == Worktree {
		msgs := r.CommitMessages(base, "HEAD")
		return msgs + "\n(+ uncommitted changes in the working tree)\n"
	}
	out := r.run("log", "--format=%h %s%n%n%b", base+".."+head)
	if out == nil {
		return ""
	}
	return *out
}

// Archive returns every file at a given revision as a tar. It only reads and writes nothing to the repository.
func (r *Repo) Archive(ref string) (io.ReadCloser, func() error, error) {
	cmd := exec.Command("git", "-C", r.Dir, "archive", "--format=tar", ref)
	cmd.Env = append(os.Environ(), "GIT_OPTIONAL_LOCKS=0")
	out, err := cmd.StdoutPipe()
	if err != nil {
		return nil, nil, err
	}
	if err := cmd.Start(); err != nil {
		return nil, nil, err
	}
	return out, cmd.Wait, nil
}

// FileStat is how much one file changed.
type FileStat struct {
	File       string
	Insertions int
	Deletions  int
	New        bool
	Deleted    bool
}

// FileStats lists the files changed from base's fork point to head, in diff order.
func (r *Repo) FileStats(base, head string) []FileStat {
	return ParseFileStats(r.RawDiff(base, head))
}

// ParseFileStats counts the added and removed lines of each file in a raw diff.
func ParseFileStats(diff string) []FileStat {
	var out []FileStat
	inHunk := false
	for _, l := range strings.Split(diff, "\n") {
		switch {
		case strings.HasPrefix(l, "diff --git "):
			name := l[strings.LastIndex(l, " b/")+3:]
			out = append(out, FileStat{File: name})
			inHunk = false
		case len(out) == 0:
		case strings.HasPrefix(l, "@@"):
			inHunk = true
		case !inHunk && strings.HasPrefix(l, "new file mode"):
			out[len(out)-1].New = true
		case !inHunk && strings.HasPrefix(l, "deleted file mode"):
			out[len(out)-1].Deleted = true
		case inHunk && strings.HasPrefix(l, "+"):
			out[len(out)-1].Insertions++
		case inHunk && strings.HasPrefix(l, "-"):
			out[len(out)-1].Deletions++
		}
	}
	return out
}
