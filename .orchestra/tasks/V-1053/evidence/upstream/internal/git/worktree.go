package git

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// Worktree is a special ref meaning "the working tree (including uncommitted changes)".
// Passing it as head reads the current files instead of a commit.
// Only files git tracks and untracked files that are not ignored are read (an .env listed in .gitignore is not).
const Worktree = "WORKTREE"

// Dirty reports whether there are uncommitted changes (including untracked files).
func (r *Repo) Dirty() bool {
	out := r.run("status", "--porcelain", "--untracked-files=normal")
	return out != nil && strings.TrimSpace(*out) != ""
}

// worktreeFiles lists the files in the working tree that may be read.
func (r *Repo) worktreeFiles() map[string]bool {
	out := r.run("ls-files", "-z", "--cached", "--others", "--exclude-standard")
	files := map[string]bool{}
	if out == nil {
		return files
	}
	for _, f := range strings.Split(*out, "\x00") {
		if f == "" {
			continue
		}
		// A file deleted but not yet committed may still be listed, yet cannot be read.
		if info, err := os.Lstat(filepath.Join(r.Dir, f)); err == nil && info.Mode().IsRegular() {
			files[f] = true
		}
	}
	return files
}

func (r *Repo) untracked() []string {
	out := r.run("ls-files", "-z", "--others", "--exclude-standard")
	if out == nil {
		return nil
	}
	return nonEmpty(strings.Split(*out, "\x00"))
}

func (r *Repo) showWorktree(file string) []string {
	if !r.worktreeFiles()[file] {
		return nil
	}
	b, err := os.ReadFile(filepath.Join(r.Dir, file))
	if err != nil {
		return nil
	}
	return strings.Split(strings.TrimSuffix(string(b), "\n"), "\n")
}

// untrackedDiff renders untracked files as a diff of newly added files.
func (r *Repo) untrackedDiff(file string) string {
	cmd := exec.Command("git", "-C", r.Dir, "--no-pager", "diff", "--no-color", "--no-ext-diff", "-U3", "--no-index", "--", os.DevNull, file)
	cmd.Env = append(os.Environ(), "GIT_OPTIONAL_LOCKS=0")
	out, err := cmd.Output()
	// --no-index exits with status 1 when there are differences.
	var exit *exec.ExitError
	if err != nil && !(errors.As(err, &exit) && exit.ExitCode() == 1) {
		return ""
	}
	return string(out)
}

func (r *Repo) worktreeDiff(base string, file ...string) string {
	mb := r.MergeBase(base, Worktree)
	args := append([]string{"diff", "--no-color", "--no-ext-diff", "-U3", mb, "--"}, file...)
	var b strings.Builder
	if out := r.run(args...); out != nil {
		b.WriteString(*out)
	}
	want := map[string]bool{}
	for _, f := range file {
		want[f] = true
	}
	for _, f := range r.untracked() {
		if len(file) == 0 || want[f] {
			b.WriteString(r.untrackedDiff(f))
		}
	}
	return b.String()
}

// worktreeID is an identifier derived from the working tree's contents (used to decide whether a saved tour can be reused).
func (r *Repo) worktreeID() string {
	h := sha256.New()
	h.Write([]byte(r.RevParse("HEAD")))
	h.Write([]byte(r.worktreeDiff("HEAD")))
	return "worktree-" + hex.EncodeToString(h.Sum(nil))[:16]
}

// worktreeStat counts the changed files and lines in a diff string.
func worktreeStat(diff string) Stat {
	var s Stat
	for _, l := range strings.Split(diff, "\n") {
		switch {
		case strings.HasPrefix(l, "diff --git "):
			s.Files++
		case strings.HasPrefix(l, "+++"), strings.HasPrefix(l, "---"):
		case strings.HasPrefix(l, "+"):
			s.Insertions++
		case strings.HasPrefix(l, "-"):
			s.Deletions++
		}
	}
	return s
}
