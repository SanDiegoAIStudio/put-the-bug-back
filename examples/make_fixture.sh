#!/bin/sh
# Build a small made-up quiz repository with fixed commit ids.
# Usage: sh examples/make_fixture.sh DIR
# DIR must not exist. Prints one line on success.

set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: sh examples/make_fixture.sh DIR" >&2
    exit 2
fi

dir=$1

if [ -e "$dir" ]; then
    echo "usage: $dir already exists" >&2
    exit 2
fi

export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME="Quinn Harbor"
export GIT_AUTHOR_EMAIL="test@example.com"
export GIT_COMMITTER_NAME="Quinn Harbor"
export GIT_COMMITTER_EMAIL="test@example.com"

mkdir "$dir"

git -C "$dir" init -q

top=$(git -C "$dir" rev-parse --show-toplevel)
dir_real=$(cd "$dir" && pwd -P)
top_real=$(cd "$top" && pwd -P)
if [ "$dir_real" != "$top_real" ]; then
    echo "refusing: git toplevel is $top_real" >&2
    exit 2
fi

commit_at() {
    GIT_AUTHOR_DATE=$1
    GIT_COMMITTER_DATE=$1
    export GIT_AUTHOR_DATE GIT_COMMITTER_DATE
    shift
    msg=$1
    shift
    git -C "$dir" add -A
    git -C "$dir" -c user.name="Quinn Harbor" -c user.email="test@example.com" -c commit.gpgsign=false commit -q -m "$msg"
    unset GIT_AUTHOR_DATE GIT_COMMITTER_DATE
}

cat > "$dir/.gitignore" <<'EOF'
__pycache__/
*.pyc
EOF

cat > "$dir/page.py" <<'EOF'
"""Result page for the Harbor Quiz, a made-up game."""

def result_page(score, total):
    title = "<h1>Harbor Quiz</h1>"

    score_line = "<p>Score: %d/%d</p>" % (score - 1, total)

    main = '<a id="main" href="/quiz/start">Try again</a>'

    share = '<a id="share" href="/share?score=0">Share</a>'

    footer = "<footer>Made by Harbor</footer>"

    parts = [title, score_line, main, share, footer]
    return "\n".join(parts) + "\n"
EOF

commit_at "2020-01-01T00:00:00+0000" "Start the Harbor Quiz result page"

cat > "$dir/page.py" <<'EOF'
"""Result page for the Harbor Quiz, a made-up game."""

def result_page(score, total):
    title = "<h1>Harbor Quiz</h1>"

    score_line = "<p>Score: %d/%d</p>" % (score - 1, total)

    main = '<button id="main">See your answers</button>'

    share = '<a id="share" href="/share?score=0">Share</a>'

    footer = "<footer>Made by Harbor</footer>"

    parts = [title, score_line, main, share, footer]
    return "\n".join(parts) + "\n"
EOF

commit_at "2020-01-02T00:00:00+0000" "Stop the main button from restarting the quiz"
git -C "$dir" tag fix-button

cat > "$dir/page.py" <<'EOF'
"""Result page for the Harbor Quiz, a made-up game."""

def result_page(score, total):
    title = "<h1>Harbor Quiz results</h1>"

    score_line = "<p>Score: %d/%d</p>" % (score - 1, total)

    main = '<button id="main">See your answers</button>'

    share = '<a id="share" href="/share?score=0">Share</a>'

    footer = "<footer>Made by Harbor</footer>"

    parts = [title, score_line, main, share, footer]
    return "\n".join(parts) + "\n"
EOF

commit_at "2020-01-03T00:00:00+0000" "Rename the result heading"

cat > "$dir/test_page.py" <<'EOF'
import unittest

from page import result_page


class ResultPageTest(unittest.TestCase):
    def test_main_button_does_not_restart(self):
        page = result_page(4, 5)
        self.assertIn("Harbor Quiz results", page)
        self.assertNotIn('href="/quiz/start"', page)
        self.assertIn('id="main"', page)

    def test_share_control_is_present(self):
        page = result_page(4, 5)
        self.assertIn('id="share"', page)

    def test_footer_names_the_quiz(self):
        page = result_page(4, 5)
        self.assertIn("Thanks for playing Harbor Quiz", page)
EOF

commit_at "2020-01-04T00:00:00+0000" "Cover the button, the share control and the footer"

cat > "$dir/page.py" <<'EOF'
"""Result page for the Harbor Quiz, a made-up game."""

def result_page(score, total):
    title = "<h1>Harbor Quiz results</h1>"

    score_line = "<p>Score: %d/%d</p>" % (score - 1, total)

    main = '<button id="main">See your answers</button>'

    share = '<a id="share" href="/share?score=%d">Share</a>' % score

    footer = "<footer>Made by Harbor</footer>"

    parts = [title, score_line, main, share, footer]
    return "\n".join(parts) + "\n"
EOF

commit_at "2020-01-05T00:00:00+0000" "Pass the earned score through the share link"
git -C "$dir" tag fix-share

cat > "$dir/page.py" <<'EOF'
"""Result page for the Harbor Quiz, a made-up game."""

def result_page(score, total):
    title = "<h1>Harbor Quiz results</h1>"

    score_line = "<p>You scored %d out of %d</p>" % (score, total)

    main = '<button id="main">See your answers</button>'

    share = '<a id="share" href="/share?score=%d">Share</a>' % score

    footer = "<footer>Made by Harbor</footer>"

    parts = [title, score_line, main, share, footer]
    return "\n".join(parts) + "\n"
EOF

cat > "$dir/test_page.py" <<'EOF'
import unittest

from page import result_page


class ResultPageTest(unittest.TestCase):
    def test_main_button_does_not_restart(self):
        page = result_page(4, 5)
        self.assertIn("Harbor Quiz results", page)
        self.assertNotIn('href="/quiz/start"', page)
        self.assertIn('id="main"', page)

    def test_share_control_is_present(self):
        page = result_page(4, 5)
        self.assertIn('id="share"', page)

    def test_score_is_the_number_earned(self):
        page = result_page(4, 5)
        self.assertIn("You scored 4 out of 5", page)

    def test_footer_names_the_quiz(self):
        page = result_page(4, 5)
        self.assertIn("Thanks for playing Harbor Quiz", page)
EOF

commit_at "2020-01-06T00:00:00+0000" "Show the score that was earned"
git -C "$dir" tag fix-score

cat > "$dir/page.py" <<'EOF'
"""Result page for the Harbor Quiz, a made-up game."""

def result_page(score, total):
    title = "<h1>Harbor Quiz results</h1>"

    score_line = "<p>You scored %d out of %d</p>" % (score, total)

    main = '<button id="main">See your answers</button>'

    share = '<a id="share" href="/share?score=%d">Share</a>' % score

    footer = "<footer>Harbor Quiz</footer>"

    parts = [title, score_line, main, share, footer]
    return "\n".join(parts) + "\n"
EOF

commit_at "2020-01-07T00:00:00+0000" "Name the quiz in the footer"
git -C "$dir" tag fix-footer

cat > "$dir/page.py" <<'EOF'
"""Result page for the Harbor Quiz, a made-up game."""

def result_page(score, total):
    title = "<h1>Harbor Quiz results</h1>"

    score_line = "<p>You scored %d out of %d</p>" % (score, total)

    main = '<button id="main">See your answers</button>'

    share = '<a id="share" href="/share?score=%d">Share</a>' % score

    footer = "<footer>Thanks for playing Harbor Quiz</footer>"

    parts = [title, score_line, main, share, footer]
    return "\n".join(parts) + "\n"
EOF

commit_at "2020-01-08T00:00:00+0000" "Thank the player in the footer"

cat > "$dir/bugs.json" <<'EOF'
{
  "bugs": [
    {
      "id": "button-link",
      "guards": "the main button does not restart the quiz",
      "test": "python3 -m unittest test_page.ResultPageTest.test_main_button_does_not_restart",
      "expect": "unexpectedly found",
      "file": "page.py",
      "find": "main = '<button id=\"main\">See your answers</button>'",
      "replace": "main = '<a id=\"main\" href=\"/quiz/start\">Try again</a>'"
    },
    {
      "id": "share-score",
      "guards": "the share control is only checked for being present",
      "test": "python3 -m unittest test_page.ResultPageTest.test_share_control_is_present",
      "expect": "FAIL: test_share_control_is_present",
      "file": "page.py",
      "find": "share = '<a id=\"share\" href=\"/share?score=%d\">Share</a>' % score",
      "replace": "share = '<a id=\"share\" href=\"/share?score=0\">Share</a>'"
    },
    {
      "id": "score-wrong-words",
      "guards": "the score line shows the number earned",
      "test": "python3 -m unittest test_page.ResultPageTest.test_score_is_the_number_earned",
      "expect": "a phrase the failure never prints",
      "file": "page.py",
      "find": "You scored %d out of %d",
      "replace": "You scored %d of %d"
    },
    {
      "id": "footer-tangled",
      "guards": "the footer names the quiz",
      "test": "python3 -m unittest test_page.ResultPageTest.test_footer_names_the_quiz",
      "expect": "FAIL: test_footer_names_the_quiz",
      "fix": "fix-footer"
    }
  ]
}
EOF

commit_at "2020-01-09T00:00:00+0000" "Keep a list of bugs to put back"

printf '%s\n' "fixture ready: $dir"
