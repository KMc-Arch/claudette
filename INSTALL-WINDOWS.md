# Installing Claudette on Windows

A walkthrough for first-time users. About 5 minutes start to finish, longer if you don't already have git, Python, Node, or Claude Code installed (the installer can install all of them for you).

---

## Before You Start

You need:

- **A Windows PC** (Windows 10 build 1809 or newer, or any Windows 11)
- **Internet connection**
- **A folder where you want claudette to live** — for example `C:\dev\` or `C:\Users\<you>\projects\`. The installer creates a `claudette\` subfolder inside whatever folder you run it from. It will not touch any of your other files.

You do **not** need administrator rights for the install itself. (Some prereqs may prompt for admin during their own install if missing.)

---

## Step 1 — Open PowerShell

1. Press the **Windows key**, type `powershell`, press **Enter**.
2. A blue window appears with a prompt that looks like:
   ```
   PS C:\Users\you>
   ```

That's PowerShell. Leave it open.

> **Note:** Don't use "Windows PowerShell ISE" or the Command Prompt (`cmd.exe`) for this step. After install, claudette works from either PowerShell or `cmd.exe` — but the installer itself is PowerShell.

---

## Step 2 — Move to the Folder Where You Want Claudette Installed

The installer creates `claudette\` *inside the folder you're currently in*. So `cd` to the parent folder first.

```powershell
cd C:\dev
```

(If `C:\dev\` doesn't exist, create it first: `mkdir C:\dev`. Or pick any other folder you like.)

After this, the installer will create `C:\dev\claudette\`.

---

## Step 3 — Paste the One-Liner

Copy this exactly, paste it into PowerShell, press **Enter**:

```powershell
iwr https://raw.githubusercontent.com/KMc-Arch/claudette/main/install.ps1 | iex
```

What this does, in plain English:

- `iwr` fetches the installer script from GitHub.
- `iex` runs it in your PowerShell session.
- The script never lands on disk as a separate file. (A copy ends up inside `claudette\` after install, but that's just because it's part of the repo.)

---

## Step 4 — If Asked, Approve Prereq Install

The installer first checks for **5 things**: `git`, `python` (3.10+), `node`, `claude` (the Claude Code CLI), and `bash`.

If any are missing, you'll see something like:

```
Missing: python, node, claude
Install automatically via winget+npm? [Y/n]
```

Press **Enter** (or type **Y**) to install them automatically. The installer uses:

- **winget** (Microsoft's official package manager — comes with Windows) for git, Python, Node.
- **npm** (comes with Node) for Claude Code.

Each install runs and reports its progress. This step takes 1-3 minutes per missing tool.

> **If you see `winget not found`:** Your Windows is too old for the auto-install path. The installer will print the URLs you need and exit. Install each tool manually, then re-run the one-liner.

> **If a prereq still shows missing after install:** the installer will tell you to **close PowerShell and open a new one**, then paste the one-liner again. This is normal — Windows sometimes needs a fresh shell to see freshly installed programs. The installer is **idempotent** — running it twice is safe.

---

## Step 5 — Watch It Acquire and Wire Up

After prereqs are confirmed, you'll see:

```
==> Acquire
Cloning into 'C:\dev\claudette'...
[OK]   Cloned to C:\dev\claudette

==> Install cdt shim
[OK]   Wrote shim: C:\dev\claudette\bin\cdt.cmd
[OK]   Added C:\dev\claudette\bin to user PATH

Done.

Next:
  1. If this is your first time, authenticate Claude Code:  claude
  2. Then start a Claudette session:  cdt

  cdt is available in this window now. New PowerShell or cmd windows
  will pick it up automatically.
```

That's it. Claudette is installed.

---

## Step 6 — Authenticate Claude Code (First Time Only)

If you've never used the `claude` command before on this machine, log in:

```powershell
claude
```

It will open a browser to sign in to your Anthropic account. Follow the prompts. Once you see the Claude prompt (`>`), you can exit by pressing **Ctrl+C** (you've now authenticated; you don't need to chat from here).

You only do this **once per machine**. Skip this step if you've already used Claude Code before.

---

## Step 7 — Start Your First Claudette Session

From the same PowerShell window (or any new PowerShell or `cmd.exe` window):

```powershell
cdt
```

This boots claudette and drops you into a Claude session. You're now talking to Claude inside a claudette-governed environment.

**Try this first thing:** type into Claude:

```
new-project my-first-thing
```

Claude will scaffold a child project inside your claudette folder. That's the canonical way to start work — every project lives as its own folder under claudette, with its own memory, work tracking, and git history.

---

## Updating Later

To pull the latest claudette:

```powershell
cd C:\dev
iwr https://raw.githubusercontent.com/KMc-Arch/claudette/main/install.ps1 | iex
```

Same one-liner. The installer detects the existing `claudette\` folder and runs `git pull` instead of re-cloning. Your projects, memory, and state are untouched.

---

## Troubleshooting

**`cdt: The term 'cdt' is not recognized...`**
You're in a window that was open *before* the install. Close it, open a new PowerShell or `cmd`, try again.

**`iwr : Could not establish trust relationship...`**
Corporate proxy or strict TLS settings. Try from a personal network, or download `install.ps1` manually from GitHub and run it: `powershell -ExecutionPolicy Bypass -File .\install.ps1`.

**Installer hangs at "Installing claude-code via npm"**
First-time `npm install -g` can be slow on Windows (1-2 min). Give it time.

**`git pull failed` on re-run**
You've made local changes inside `claudette\`. Either commit/stash them, or delete the `claudette\` folder and re-run.

**I want a different folder name (not `claudette`)**
Use the parameterized form:
```powershell
& ([scriptblock]::Create((iwr 'https://raw.githubusercontent.com/KMc-Arch/claudette/main/install.ps1').Content)) -Name myname
```
This installs to `.\myname\` instead of `.\claudette\`. The `cdt` command name doesn't change.

---

## What Got Installed Where

| Path | What it is |
|---|---|
| `C:\dev\claudette\` | The framework itself (cloned from GitHub) |
| `C:\dev\claudette\bin\cdt.cmd` | The `cdt` command |
| User PATH | Now includes `C:\dev\claudette\bin\` |
| Your projects | Will be created as subfolders of `C:\dev\claudette\` when you run `new-project` |

To uninstall: delete `C:\dev\claudette\`, and remove that path from your user PATH (PowerShell: `[Environment]::SetEnvironmentVariable('Path', ([Environment]::GetEnvironmentVariable('Path','User') -replace [regex]::Escape(';C:\dev\claudette\bin'),''), 'User')`).
