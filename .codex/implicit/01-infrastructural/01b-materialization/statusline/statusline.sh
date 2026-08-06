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
effort=$(jq -r '.effortLevel // empty' ~/.claude/settings.json 2>/dev/null)
thinking=$(jq -r '.alwaysThinkingEnabled // empty' ~/.claude/settings.json 2>/dev/null)
dir=$(basename "$cwd" 2>/dev/null || echo "?")

# --- Location: 🏠 launch dir, 📁 path relative to it ---
# 📁 is ^-relative, where ^ is the session's own root (workspace.project_dir) —
# the same anchor gravity-guard.sh and boot-inject.py resolve ^ to. Neither the
# ^ nor ^/^ literal is printed; real folder names are.
#
# The nearest root: true ancestor is still resolved, but it colours 🏠 rather
# than moving the path. Crossing into a child project is worth flagging; it is
# not worth silently re-anchoring 📁 onto a root the guards don't share.
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
    for ((i=0; i<12; i++)); do
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
        launch_label="🏠${launch_name}"
        dir="$launch_name"
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
if [[ -n "$cwd" && -d "$cwd" ]]; then
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
    # Single-pass transcript extraction: context tokens + last user message
    _transcript_data=$(jq -s '
        def is_unhelpful:
            startswith("[Request interrupted") or
            startswith("[Request cancelled") or
            . == "";
        {
            context_length: (
                map(select(.message.usage and .isSidechain != true and .isApiErrorMessage != true)) |
                last |
                if . then
                    (.message.usage.input_tokens // 0) +
                    (.message.usage.cache_read_input_tokens // 0) +
                    (.message.usage.cache_creation_input_tokens // 0) +
                    (.message.usage.output_tokens // 0)
                else 0 end
            ),
            last_user_msg: (
                [.[] | select(.type == "user") |
                 select(.message.content | type == "string" or
                        (type == "array" and any(.[]; .type == "text")))] |
                reverse |
                map(.message.content |
                    if type == "string" then .
                    else [.[] | select(.type == "text") | .text] | join(" ") end |
                    gsub("\n"; " ") | gsub("  +"; " ")) |
                map(select(is_unhelpful | not)) |
                first // ""
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

    bar=""
    for ((i=0; i<bar_width; i++)); do
        bar_start=$((i * 10))
        progress=$((pct - bar_start))
        if [[ $progress -ge 8 ]]; then
            bar+="${C_ACCENT}█${C_RESET}"
        elif [[ $progress -ge 3 ]]; then
            bar+="${C_ACCENT}▄${C_RESET}"
        else
            bar+="${C_BAR_EMPTY}░${C_RESET}"
        fi
    done

    ctx="${bar} ${C_GRAY}${pct_prefix}${pct}% of ${max_k}k tokens"
else
    baseline=20000
    bar_width=10
    pct=$((baseline * 100 / max_context))
    [[ $pct -gt 100 ]] && pct=100

    bar=""
    for ((i=0; i<bar_width; i++)); do
        bar_start=$((i * 10))
        progress=$((pct - bar_start))
        if [[ $progress -ge 8 ]]; then
            bar+="${C_ACCENT}█${C_RESET}"
        elif [[ $progress -ge 3 ]]; then
            bar+="${C_ACCENT}▄${C_RESET}"
        else
            bar+="${C_BAR_EMPTY}░${C_RESET}"
        fi
    done

    ctx="${bar} ${C_GRAY}~${pct}% of ${max_k}k tokens"
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
output+=" | ${ctx}${C_RESET}"

printf '%b\n' "$output"

# --- Last user message ---
if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
    plain_output="${model}"
    [[ -n "$launch_plain" ]] && plain_output+=" | ${launch_plain}"
    [[ -n "$dir" ]] && plain_output+=" | ${dir}"
    [[ -n "$project_info" ]] && plain_output+=" | ${project_id} [xxxxxxx]"
    [[ -n "$branch" ]] && plain_output+=" | ${branch} ${git_status}"
    plain_output+=" | xxxxxxxxxx ${pct}% of ${max_k}k tokens"
    max_len=${#plain_output}
    # last_user_msg already extracted in single-pass above
    if [[ -n "$last_user_msg" ]]; then
        if [[ ${#last_user_msg} -gt $max_len ]]; then
            echo "💬 ${last_user_msg:0:$((max_len - 3))}..."
        else
            echo "💬 ${last_user_msg}"
        fi
    fi
fi
