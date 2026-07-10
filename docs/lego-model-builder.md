# LEGO Model Builder

The LEGO Model Builder skill turns a description such as “make a small red
lighthouse” into a LEGO model you can view, share, and change. You describe
the idea in ordinary language; the skill chooses parts, builds the model,
checks it for problems, and gives you the finished files.

[Download LEGO Model Builder](https://hbmartin.github.io/pyldraw3/downloads/lego-model-builder.zip){ .md-button .md-button--primary }

Keep the download as a ZIP file. You do not need to open or unpack it before
installing it.

## Before you install

The skill needs an app that supports custom skills and can run code. It also
needs access to Python 3.12 or newer in the environment where it runs.

The first model takes longer because the skill may need to:

- install `pyldraw3`;
- download the LDraw parts library (about 80 MB); and
- install or find an app that can make preview images.

Allow these installations only in an environment where you are comfortable
letting the skill add software. Later models reuse this setup and should start
more quickly.

## Install in the ChatGPT desktop app

Custom Skills are available only on eligible ChatGPT plans and may be disabled
by your workspace administrator. See OpenAI's
[Skills in ChatGPT guide](https://help.openai.com/en/articles/20001066) for the
current availability and workspace settings.

1. Download `lego-model-builder.zip` using the button above.
2. Open the ChatGPT desktop app and select your profile icon.
3. Select **Skills**.
4. Select **Create**, then **Upload from your computer**.
5. Choose `lego-model-builder.zip` from your Downloads folder.
6. Wait while ChatGPT checks the skill, then follow any review prompt it shows.

Personal Skills installed in the ChatGPT desktop app do not automatically sync
to ChatGPT on the web or mobile. Upload the ZIP separately on each surface
where you want to use it.

## Install in the Claude desktop app

Claude requires **Code execution and file creation** to be enabled before it
can use Skills. See Anthropic's
[Use skills in Claude guide](https://support.claude.com/en/articles/12512180-use-skills-in-claude)
for the current plan and organization settings.

1. Download `lego-model-builder.zip` using the button above.
2. For an individual account, open **Settings → Capabilities** and enable
   **Code execution and file creation**. On a Team or Enterprise workspace, an
   owner may need to enable this under **Organization settings → Skills**.
3. Open **Customize → Skills**.
4. Select **+**, then **Create skill**.
5. Select **Upload a skill** and choose `lego-model-builder.zip` from your
   Downloads folder.
6. Make sure LEGO Model Builder is switched on in your Skills list.

## Build your first model

Start a new conversation and paste this prompt:

```text
Use the LEGO Model Builder skill to make a small red and white lighthouse.
Keep it under 16 × 16 studs, use a simple blocky style, and put it on a base.
```

The skill may ask about the size, colors, level of detail, or features that
matter most. You can answer approximately—“small enough for a desk” or “mostly
blue” is enough to get started.

Other requests you can try:

- “Build a yellow duck in a simple, blocky style, about 12 studs long.”
- “Make a moon rover with six wheels, a white body, and gold details.”
- “Create a castle gate on a 24-stud-wide base with two gray towers.”
- “Build a red wall that is 8 studs wide and 3 bricks tall.”

Including a subject, approximate size, colors, style, and any must-have feature
helps the skill make a better first version. You can also attach a reference
image and explain which details you want it to follow.

## What the skill does

For each request, the skill:

1. asks for any important missing details;
2. chooses real LDraw parts and lays them out as a model;
3. creates a reusable Python program and an LDraw model file;
4. checks the model for invalid, duplicate, or floating pieces;
5. renders front, angled, and top preview images when a renderer is available;
6. improves the model based on those checks and previews; and
7. returns the files and a bill of materials listing the parts used.

The skill limits its preview-and-fix loop to a few passes. If something is
still imperfect, it will describe the remaining limitation instead of working
indefinitely.

## Files you receive

The model name is shortened into a file-friendly name. A “red lighthouse”
request might produce:

| File | What it is for |
| --- | --- |
| `red-lighthouse.ldr` | The finished LEGO model. Open it in LDView, LeoCAD, or BrickLink Studio. |
| `red-lighthouse.py` | The reusable recipe that created the model. Its named settings can be changed and run again. |
| `red-lighthouse.front.png` | A preview from the front. |
| `red-lighthouse.iso.png` | An angled preview that shows several sides. |
| `red-lighthouse.top.png` | A preview from above. |

The files are created in the skill's current working folder. In a desktop app,
ask the assistant to attach the `.ldr`, `.py`, and preview files if download
links are not already shown.

When the skill renders the same views again, it moves the prior preview images
into a timestamped folder under `previous/`. This keeps each earlier preview
set available for comparison without confusing it with the newest images.

The `.ldr` file is the main deliverable. It uses the open LDraw model format
and can be opened in LEGO CAD programs including
[LDView](https://tcobbs.github.io/ldview/),
[LeoCAD](https://www.leocad.org/), and
[BrickLink Studio](https://www.bricklink.com/v3/studio/download.page).

## If preview images cannot be created

The skill first looks for LDView or LeoCAD. If it cannot find or install either
renderer, it switches to **validate-only mode**. It still creates the Python
and `.ldr` files, checks the model, and produces a bill of materials, but it
cannot inspect preview images.

The `.ldr` file is still usable. Open it in one of the LEGO CAD programs above
to inspect the model visually.

## Troubleshooting

### ChatGPT does not show Skills

Check that your ChatGPT plan supports Personal Skills and that your workspace
administrator has enabled creating and uploading Skills. If you installed the
skill on the web or mobile, remember that you must install it separately in
the desktop app.

### ChatGPT shows Needs Review or Blocked

ChatGPT checks uploaded Skills before making them available. Read the review
details and confirm that you trust this project's scripts and downloads. A
skill marked **Blocked** cannot be used; consult your workspace administrator
or the official ChatGPT Skills guide.

### Claude does not show Skills, or the skill is gray

Enable **Code execution and file creation** in **Settings → Capabilities**. On
a Team or Enterprise workspace, ask an owner to check **Organization settings
→ Skills**. Return to **Customize → Skills** and make sure LEGO Model Builder
is switched on.

### The ZIP will not upload

Download the ZIP again and upload it without unpacking it. Make sure you chose
`lego-model-builder.zip`, not one of the files inside it. If an organization
manages your account, it may also restrict custom Skill uploads.

### The skill says Python 3.12 is required

The skill could not find a new enough Python interpreter in its working
environment. Install Python 3.12 or newer there, or move the task to an
environment that already provides it, then ask the skill to try again.

### The first build appears to be stuck

The first run may download about 80 MB of LEGO parts and install rendering
software. Ask the assistant for the current setup status before stopping it.
Later builds should reuse the downloaded files.

### No preview images appear

Look for a message saying the build used validate-only mode. The `.ldr` file
should still be available and can be opened in LDView, LeoCAD, or BrickLink
Studio. On a local computer, installing LDView or LeoCAD enables previews on a
later run.

### The assistant does not choose the skill

Name it explicitly: “Use the LEGO Model Builder skill to build …” Then check
that the skill is installed and enabled in the app's Skills list.

## Trust, downloads, and privacy

A Skill can contain instructions and executable scripts. Install it only if
you trust this project and are comfortable with the actions it performs.

LEGO Model Builder may install `pyldraw3`, download the LDraw parts library,
and install rendering software through the package manager available in its
working environment. These actions can write to configuration, cache, and
application-data folders. Review requests for permission before approving
them, especially on a work-managed computer.

Your model description, reference images, and generated files are also subject
to the privacy and data-handling policies of the desktop app and workspace you
use.

## Advanced installation

Users of coding agents that support the Agent Skills format can install the
skill directly from GitHub:

```bash
npx skills add hbmartin/pyldraw3 --skill lego-model-builder
```
