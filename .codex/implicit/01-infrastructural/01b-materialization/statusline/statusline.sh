#!/usr/bin/env bash

# Ensure jq is on PATH
if ! command -v jq &>/dev/null; then
    JQ_DIR=$(find "$LOCALAPPDATA/Microsoft/WinGet/Packages" -maxdepth 1 -name 'jqlang.jq_*' -print -quit 2>/dev/null)
    [[ -n "$JQ_DIR" ]] && export PATH="$PATH:$JQ_DIR"
fi
if ! command -v jq &>/dev/null; then
    echo "statusline: jq not found"
    exit 0
fi

# Color theme: gray, orange, blue, teal, green, lavender, rose, gold, slate, cyan
COLOR="blue"

# Color codes
C_RESET='\033[0m'
C_GRAY='\033[38;5;245m'
C_BAR_EMPTY='\033[38;5;238m'
C_WARN='\033[38;5;208m'
C_CAUTION='\033[38;5;220m'
case "$COLOR" in
    orange)   C_ACCENT='\033[38;5;173m' ;;
    blue)     C_ACCENT='\033[38;5;74m' ;;
    teal)     C_ACCENT='\033[38;5;66m' ;;
    green)    C_ACCENT='\033[38;5;71m' ;;
    lavender) C_ACCENT='\033[38;5;139m' ;;
    rose)     C_ACCENT='\033[38;5;132m' ;;
    gold)     C_ACCENT='\033[38;5;136m' ;;
    slate)    C_ACCENT='\033[38;5;60m' ;;
    cyan)     C_ACCENT='\033[38;5;37m' ;;
    *)        C_ACCENT="$C_GRAY" ;;
esac

input=$(cat)

# Extract model, directory, cwd, and effort
model=$(echo "$input" | jq -r '.model.display_name // .model.id // "?"')
cwd=$(echo "$input" | jq -r '.cwd // empty')
project_dir=$(echo "$input" | jq -r '.workspace.project_dir // empty')

# --- Normalize path separators to "/" ONCE, up front, before ANY path logic. ---
# RECURRENT PITFALL — this line keeps getting dropped when this file is copied
# or rewritten. DO NOT remove it. On Windows / Git-Bash the harness can hand
# cwd/project_dir with "\" separators (and can even mix "\" and "/" for the same
# real folder). Everything below assumes "/": the _elide relativizer, the
# "$launch_dir"/* and nearest-root prefix globs, and the final `printf '%b'`
# (which turns \033[ colour codes into real escapes). A stray literal "\" that
# reaches that printf is read as a bad escape (e.g. "\Users" -> \U) and
# TRUNCATES the rest of the status line. Normalizing here is what prevents it.
cwd="${cwd//\\//}"
project_dir="${project_dir//\\//}"

effort=$(echo "$input" | jq -r '.effort.level // empty')
thinking=$(echo "$input" | jq -r '.thinking.enabled // empty')
dir=$(basename "$cwd" 2>/dev/null || echo "?")

# Extract 5h rate-limit window (added: quota bar)
five_h_pct=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
five_h_resets=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')

# --- Location: 🏠 launch dir, 📁 path relative to it ---
# Both anchor on workspace.project_dir, the raw launch directory. That is NOT
# where the guards resolve ^ any more: since BL-35 containment-guard.sh and
# gravity-guard.sh walk UP from $CLAUDE_PROJECT_DIR to the nearest declared
# root, so when the session is launched below a root their ceiling sits above
# what this bar prints. (boot-inject.py still uses the raw launch dir — BL-38.)
# Neither the ^ nor ^/^ literal is printed; real folder names are.
#
# The nearest root: true ancestor IS resolved here, but it only colours 🏠 —
# re-anchoring 📁 on it would render "demo" for zMisc/demo and hide the
# traversal. Colour carries the same fact without that cost.
#
# This detector is deliberately STRICTER (narrower) than the guards' and the
# frontmatter.md grammar — bare lowercase `root: true` only, no BOM, quotes,
# `True`/`yes`, or trailing comment. That is the opposite of what a FENCE may do
# (a fence must be at least as permissive as the grammar, or it walks past a real
# root to a looser ceiling). It is allowed here because this is a display HINT,
# not a fence: under-recognising a root only mis-tints an emoji. frontmatter.md's
# permissive-not-strict rule is explicitly scoped to enforcement contexts.
_is_root() {
    [[ -f "$1" ]] || return 1
    # Frontmatter only: first --- fence to the next. A body mention doesn't count.
    awk 'NR==1 { if ($0 !~ /^---[[:space:]]*$/) exit 1; next }
         /^---[[:space:]]*$/ { exit }
         { print }' "$1" 2>/dev/null |
        grep -qE '^[[:space:]]*(apex-)?root[[:space:]]*:[[:space:]]*true[[:space:]]*$'
}

# Nearest root: true / apex-root: true ancestor, inclusive of the start dir.
_nearest_root() {
    local d="$1" p
    [[ -n "$d" ]] || return 1
    # Terminate on dirname reaching a fixed point, matching the guards and the
    # spec (frontmatter.md walks to the filesystem root). The old 12-level cap
    # silently reported "no root" past that depth, so the tint stopped flagging
    # a crossed child-project boundary.
    while :; do
        _is_root "$d/CLAUDE.md" && { echo "$d"; return 0; }
        p=$(dirname "$d")
        [[ "$p" == "$d" ]] && break
        d="$p"
    done
    return 1
}

# Middle-truncate a path so the bar doesn't wrap, keeping both informative ends.
_elide() {
    local p="$1"
    if [[ ${#p} -gt 32 && "$p" == */* ]]; then
        echo "${p%%/*}/…/${p##*/}"
    else
        echo "$p"
    fi
}

# Render a fixed-width block bar for a 0-100 percentage. Shared by every
# budget-style metric (context window, rate-limit windows) so they read as
# one visual family instead of separate lookalikes.
_render_bar() {
    local pct=$1 width=$2 bar="" i bar_start progress
    for ((i=0; i<width; i++)); do
        bar_start=$((i * 100 / width))
        progress=$((pct - bar_start))
        if [[ $progress -ge $((100 / width * 8 / 10)) ]]; then
            bar+="${C_ACCENT}█${C_RESET}"
        elif [[ $progress -ge $((100 / width * 3 / 10)) ]]; then
            bar+="${C_ACCENT}▄${C_RESET}"
        else
            bar+="${C_BAR_EMPTY}░${C_RESET}"
        fi
    done
    echo "$bar"
}

# Format a seconds count as "Xd Yh" / "Xh Ym" / "Xm Ys" depending on
# magnitude. Shared by rate-limit reset countdowns and session duration.
_fmt_secs() {
    local s=$1
    [[ $s -lt 0 ]] && s=0
    if   [[ $s -ge 86400 ]]; then echo "$((s / 86400))d $(( (s % 86400) / 3600 ))h"
    elif [[ $s -ge 3600 ]];  then echo "$((s / 3600))h $(( (s % 3600) / 60 ))m"
    else                          echo "$((s / 60))m $((s % 60))s"
    fi
}

launch_label=""
launch_plain=""
if [[ -n "$cwd" ]]; then
    # ^ for display purposes: the session root, falling back to the nearest
    # declared root and finally to cwd itself.
    launch_dir="$project_dir"
    [[ -z "$launch_dir" ]] && launch_dir=$(_nearest_root "$cwd")
    [[ -z "$launch_dir" ]] && launch_dir="$cwd"

    launch_name=$(basename "$launch_dir")
    launch_plain="🏠${launch_name}"
    nearest=$(_nearest_root "$cwd")

    if [[ "$cwd" == "$launch_dir" ]]; then
        dir="$launch_name"
        if [[ -n "$nearest" && "$nearest" != "$launch_dir" ]]; then
            # Launched BELOW a root: the guards' ceiling sits above 🏠, and no
            # field names it — so tint 🏠 to flag that ^ is not the launch dir.
            launch_label="${C_CAUTION}🏠${launch_name}${C_GRAY}"
        else
            launch_label="🏠${launch_name}"
        fi
    elif [[ "$cwd" == "$launch_dir"/* ]]; then
        dir=$(_elide "${cwd#"$launch_dir"/}")
        if [[ -n "$nearest" && "$nearest" != "$launch_dir" ]]; then
            # Inside ^ but past a root: true boundary — a child project
            launch_label="${C_CAUTION}🏠${launch_name}${C_GRAY}"
        else
            launch_label="🏠${launch_name}"
        fi
    else
        # Left ^ entirely: 📁 now names a folder in another project, so anchor
        # it on whatever root cwd actually sits under
        launch_label="${C_WARN}🏠${launch_name}${C_GRAY}"
        if [[ -n "$nearest" ]]; then
            nearest_name=$(basename "$nearest")
            if [[ "$cwd" == "$nearest" ]]; then
                dir="$nearest_name"
            else
                dir=$(_elide "${nearest_name}/${cwd#"$nearest"/}")
            fi
        fi
    fi
fi

# --- Project context from ProjectMetaBase.db ---
project_info=""
if [[ -n "$cwd" ]]; then
    # Walk up from cwd looking for ProjectMetaBase.db
    db_path=""
    search_dir="$cwd"
    for ((d=0; d<5; d++)); do
        if [[ -f "$search_dir/ProjectMetaBase.db" ]]; then
            db_path="$search_dir/ProjectMetaBase.db"
            break
        fi
        parent=$(dirname "$search_dir")
        [[ "$parent" == "$search_dir" ]] && break
        search_dir="$parent"
    done

    if [[ -n "$db_path" ]]; then
        # Determine which project we're in by checking if cwd is under a project folder
        # Get the relative path from the db root to cwd
        db_root=$(dirname "$db_path")
        rel_path="${cwd#$db_root/}"

        # Try to match: type/project or type/project/deeper
        project_id=""
        project_type=""
        if [[ "$rel_path" == *"/"* ]]; then
            project_type=$(echo "$rel_path" | cut -d'/' -f1)
            project_id=$(echo "$rel_path" | cut -d'/' -f2)
        fi

        # Validate project_id — reject anything that isn't a safe identifier
        if [[ -n "$project_id" && ! "$project_id" =~ ^[a-zA-Z0-9_-]+$ ]]; then
            project_id=""
        fi

        if [[ -n "$project_id" ]]; then
            # Query project status and last run phase
            proj_row=$(sqlite3 "$db_path" "
                SELECT p.status,
                       (SELECT phase FROM trans_runs
                        WHERE project_id = p.project_id
                        ORDER BY started_at DESC LIMIT 1)
                FROM core_projects p
                WHERE p.project_id = '$project_id'
            " 2>/dev/null)

            if [[ -n "$proj_row" ]]; then
                proj_status=$(echo "$proj_row" | cut -d'|' -f1)
                last_phase=$(echo "$proj_row" | cut -d'|' -f2)

                # Count new context files (not yet analyzed)
                new_files=$(sqlite3 "$db_path" "
                    SELECT COUNT(*) FROM core_context_files
                    WHERE project_id = '$project_id'
                    AND first_analyzed_in_run_id IS NULL
                " 2>/dev/null)

                # Build project info string
                phase_str=""
                [[ -n "$last_phase" ]] && phase_str="$last_phase"
                [[ -z "$last_phase" ]] && phase_str="no runs"

                project_info="${C_ACCENT}${project_id}${C_GRAY} [${phase_str}]"

                if [[ "$new_files" -gt 0 ]]; then
                    project_info+=" ${C_WARN}+${new_files} new${C_GRAY}"
                fi
            else
                # Folder exists under a type but isn't registered yet
                project_info="${C_WARN}${project_id}${C_GRAY} [unregistered]"
            fi
        else
            # We're at root or type level, show workspace summary
            active_count=$(sqlite3 "$db_path" "
                SELECT COUNT(*) FROM core_projects WHERE status = 'active'
            " 2>/dev/null)
            if [[ -n "$active_count" ]]; then
                project_info="${C_GRAY}${active_count} active projects"
            fi
        fi
    fi
fi

# --- Git info (conditional, only if in a git repo) ---
branch=""
git_status=""
if [[ -n "$cwd" && -d "$cwd" ]] && ! git -C "$cwd" check-ignore -q . 2>/dev/null; then
    branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
    if [[ -n "$branch" ]]; then
        file_count=$(git -C "$cwd" --no-optional-locks status --porcelain -unormal 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$file_count" -eq 0 ]]; then
            git_status="(clean)"
        else
            git_status="(${file_count} uncommitted)"
        fi
    fi
fi

# --- Context bar ---
transcript_path=$(echo "$input" | jq -r '.transcript_path // empty')
max_context=$(echo "$input" | jq -r '.context_window.context_window_size // 200000')
[[ "$max_context" =~ ^[0-9]+$ && "$max_context" -gt 0 ]] || max_context=200000
max_k=$((max_context / 1000))

if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
    # Single-pass transcript extraction: context tokens + last user message.
    #
    # Parse LINE-BY-LINE (`jq -nR '[inputs | fromjson? // empty]'`), NOT `jq -s`.
    # `jq -s` aborts the WHOLE parse on one malformed line, and transcripts on
    # this 9p mount can carry runs of NUL bytes mid-file. When that happened the
    # 💬 row vanished AND context_length fell to 0 (rendering the fake ~2%
    # baseline instead of the real fill). `fromjson? // empty` drops only the bad
    # line. Benchmarked free (23ms vs 25ms on the largest transcript here).
    #
    # last_user_msg is a WHITELIST, not a blacklist. Claude Code writes many
    # things as type:"user" — task-notifications, hook/meta payloads, tool
    # results, sdk/auto-continuation entries — and a blacklist has to chase every
    # new kind (auto-continuation already appeared). Every real human prompt
    # carries origin.kind=="human" (or, for one legacy shape, promptSource=="typed");
    # nothing else does. So: keep human-origin/typed, drop isMeta/isSidechain/
    # toolUseResult. On 2.1.251 a typed slash command records with NO origin, so
    # it is correctly skipped and the row holds the previous real prompt; older
    # transcripts tagged them "human" as raw <command-name> XML — unwrap those.
    _transcript_data=$(jq -nR '
        [inputs | fromjson? // empty] as $es
        | {
            context_length: (
                $es
                | map(select(.message.usage and .isSidechain != true and .isApiErrorMessage != true))
                | last
                | if . then (.message.usage.input_tokens // 0) + (.message.usage.cache_read_input_tokens // 0)
                           + (.message.usage.cache_creation_input_tokens // 0) + (.message.usage.output_tokens // 0)
                  else 0 end
            ),
            last_user_msg: (
                $es
                | map(select(.type == "user"
                             and (.isMeta // false) != true
                             and (.isSidechain // false) != true
                             and (.toolUseResult | not)
                             and (.origin.kind == "human" or .promptSource == "typed")))
                | reverse
                | map(.message.content
                      | if type == "string" then .
                        else [.[]? | select(.type == "text") | .text] | join("\n") end)
                | map(if test("<command-name>") then
                        ((capture("<command-name>(?<n>[^<]*)</command-name>").n // "")
                         + (((capture("<command-args>(?<a>[^<]*)</command-args>").a) // "")
                            | if . == "" then "" else " " + . end))
                      else . end)
                | map(select(test("^[[:space:]]*$") | not))
                | map(select(startswith("[Request interrupted") or startswith("[Request cancelled") | not))
                | first // ""
            )
        }
    ' < "$transcript_path" 2>/dev/null)
    context_length=$(echo "$_transcript_data" | jq -r '.context_length')
    last_user_msg=$(echo "$_transcript_data" | jq -r '.last_user_msg')
    [[ "$context_length" =~ ^[0-9]+$ ]] || context_length=0

    baseline=20000
    bar_width=10

    if [[ "$context_length" -gt 0 ]]; then
        pct=$((context_length * 100 / max_context))
        pct_prefix=""
    else
        pct=$((baseline * 100 / max_context))
        pct_prefix="~"
    fi

    [[ $pct -gt 100 ]] && pct=100

    bar=$(_render_bar "$pct" "$bar_width")
    ctx="${bar} ${C_GRAY}${pct_prefix}${pct}% of ${max_k}k tokens"
else
    baseline=20000
    bar_width=10
    pct=$((baseline * 100 / max_context))
    [[ $pct -gt 100 ]] && pct=100

    bar=$(_render_bar "$pct" "$bar_width")
    ctx="${bar} ${C_GRAY}~${pct}% of ${max_k}k tokens"
fi

# --- Budget bar: 5h rate-limit window, same style/width as the context bar ---
# Absent pre-first-response and for non-Pro/Max accounts.
quota_line=""
if [[ -n "$five_h_pct" ]]; then
    five_h_int=${five_h_pct%.*}
    five_h_bar=$(_render_bar "$five_h_int" 10)
    five_h_left=""
    [[ -n "$five_h_resets" ]] && five_h_left=" (${C_GRAY}$(_fmt_secs $((five_h_resets - $(date +%s))))${C_RESET})"
    quota_line="⏳${five_h_bar} ${C_GRAY}${five_h_int}%${C_RESET}${five_h_left}"
fi

# --- Build output ---
# Effort label
effort_label=""
if [[ -n "$effort" ]]; then
    case "$effort" in
        low)    effort_label=" ${C_GRAY}⚡lo" ;;
        medium) effort_label=" ${C_GRAY}⚡md" ;;
        high)   effort_label=" ${C_GRAY}⚡hi" ;;
        xhigh)  effort_label=" ${C_GRAY}⚡xh" ;;
        max)    effort_label=" ${C_GRAY}⚡mx" ;;
    esac
fi

# Thinking indicator
thinking_label=""
if [[ "$thinking" == "true" ]]; then
    thinking_label=" ${C_GRAY}💭on"
else
    thinking_label=" ${C_GRAY}💭off"
fi

output="${C_ACCENT}${model}${effort_label}${thinking_label}${C_GRAY}"
[[ -n "$launch_label" ]] && output+=" | ${launch_label}"
[[ -n "$dir" ]] && output+=" | 📁${dir}"
[[ -n "$project_info" ]] && output+=" | ${project_info}"
[[ -n "$branch" ]] && output+=" | 🔀${branch} ${git_status}"
output+=" | ${ctx}"
[[ -n "$quota_line" ]] && output+=" | ${quota_line}"
output+="${C_RESET}"

printf '%b\n' "$output"

# --- Second row: 💬 last user message ---
# Render the prompt's first non-empty line, then keep appending the following
# non-empty lines (joined by ⏎) until the terminal width runs out. A strict
# first-line-only rule loses too much (a scoping prompt whose real question is two
# lines down); appending until full keeps the useful head of a multi-line prompt.
#
# Width is $COLUMNS, which Claude Code sets to the live terminal size before
# running the script — `tput cols` and language-level detection cannot work here
# because the script's stdout is captured, not attached to the terminal (docs).
# Fallback when COLUMNS is somehow unset: the plain-text width of row 1 (what
# shipped before). The budget reserves the "💬 " prefix plus a 1-col gap so the
# row never reaches the edge and wraps.
if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
    plain_output="${model}"
    [[ -n "$launch_plain" ]] && plain_output+=" | ${launch_plain}"
    [[ -n "$dir" ]] && plain_output+=" | ${dir}"
    [[ -n "$project_info" ]] && plain_output+=" | ${project_id} [xxxxxxx]"
    [[ -n "$branch" ]] && plain_output+=" | ${branch} ${git_status}"
    plain_output+=" | xxxxxxxxxx ${pct}% of ${max_k}k tokens"
    width=${COLUMNS:-${#plain_output}}
    budget=$((width - 4))
    [[ $budget -lt 20 ]] && budget=20
    # last_user_msg already extracted in single-pass above; newlines preserved.
    if [[ -n "$last_user_msg" ]]; then
        out=""
        while IFS= read -r line; do
            # trim leading/trailing whitespace; skip blank lines
            line="${line#"${line%%[![:space:]]*}"}"
            line="${line%"${line##*[![:space:]]}"}"
            [[ -z "$line" ]] && continue
            if [[ -z "$out" ]]; then
                out="$line"
            else
                cand="$out ⏎ $line"
                [[ ${#cand} -gt $budget ]] && break
                out="$cand"
            fi
            [[ ${#out} -ge $budget ]] && break
        done <<< "$last_user_msg"
        [[ ${#out} -gt $budget ]] && out="${out:0:$((budget - 3))}..."
        [[ -n "$out" ]] && echo "💬 $out"
    fi
fi
