---
name: web-forms
description: >
  Load BEFORE the first click of any web form or application portal: "apply to this job",
  "fill out the application", Workday, UltiPro/UKG, iCIMS, Oracle, CalCareers, any ATS.
  Technique for the playwright MCP: dropdowns, comboboxes, typeaheads and date pickers that
  silently take the wrong value, the stale-ref trap, keyboard-first selection, the React
  native-setter fallback, file uploads, and what is never Claude's click.
---

# Web forms with the playwright MCP

Most "the form will not take it" failures are one of three mistakes: treating a custom JS
widget like a native control, acting on refs after the DOM changed, or batch-filling and
checking at the end. Fix those and most forms fall.

## Ground rules

1. **Refs from a fresh snapshot.** `browser_snapshot` gives the accessibility tree with refs;
   act on those (`browser_click`, `browser_type`, `browser_select_option`). Coordinates are a
   last resort.
2. **Refs go stale when the DOM changes.** Opening a dropdown, typing into an autocomplete, or a
   re-render invalidates the tree. Snapshot again after every action that changes the page.
3. **One field at a time, verify each.** After setting a field, read its value back from a
   snapshot or `browser_evaluate` (`el.value`). A screenshot can show a value the framework
   never registered. Never fill ten fields blind and check at the end.
4. **Never re-navigate mid-form.** Unsubmitted state usually dies with the page.
5. **Read `references/site-notes.md` before the first click.** It is short and it is where the
   traps for already-conquered hosts live; they bite during filling, not after.
6. **Prefer "apply manually" over "autofill with resume".** A parser writes claims in the
   applicant's name (skill levels, dates, titles) that you then have to find and fix.

## Step 1: diagnose the widget

In the snapshot, look at the role:
- A real `<select>`: `browser_select_option` with the option text or value. Done.
- `combobox` or a `textbox` that filters as you type (React-Select, MUI, Workday, Greenhouse):
  the hard case, below.
- An input with a calendar icon: date picker, below.
- A checkbox that is a styled div: click, then verify `checked` in the snapshot; if the tree
  says `active` but never `checked`, read `input.checked` with `browser_evaluate`.

## Step 2: route by widget

**Custom combobox, keyboard first.** Click the control to open it; `browser_type` the first few
characters (most comboboxes filter); snapshot; confirm the option is in the listbox; ArrowDown
and Enter (`browser_press_key`); snapshot; confirm the control shows the value. Options render
into a portal at the END of the document, outside the control's subtree, and exist only while
open. If the list is virtualized (about ten options visible), type-to-filter is the only
reliable path.

**Not on a single-page form.** On a form whose Submit button is on the page being filled and
that keeps no saved state (Greenhouse-hosted forms, most no-account apply pages), never press
Enter in a field: if the list has closed or never opened, Enter in a text input is the
browser's implicit form submit, and the application goes out half filled. Type to filter, then
`browser_click` the option. Note the URL path before filling and confirm it is unchanged
after. Multi-step wizards with their own Next button (Workday) are the normal case for Enter.

**Click-the-option** when typing does not filter, and always on a single-page form: open,
snapshot, find the `option` role near the bottom of the tree, click it, verify.

**Date pickers.** Type the date in the format the placeholder shows, then Tab or Escape to close
the calendar. Drive the grid only if typed text is rejected; snapshot after every month click.
Some portals hide the real input behind a display div (Workday: see site notes).

**Typeaheads with pills** (school, field of study, license): type, wait for the suggestion,
click the suggestion (or press Enter, in a multi-step wizard only), verify the pill.

**Search boxes that swallow the first keystrokes.** Click the box alone first, snapshot to see
it expanded, then type in a second call.

## Step 3: fallback for widgets that resist everything

React and similar frameworks ignore a plain `.value =`. Through `browser_evaluate`:

```js
const el = document.querySelector('SELECTOR');
const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el).constructor.prototype, 'value').set;
setter.call(el, 'VALUE');
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
```

Verify afterwards that the app state took it (the displayed value updates and dependent fields
react). Knockout apps (UltiPro) accept a plain value plus a bubbling change event; confirm with
`ko.dataFor(el)` before relying on it. Shadow DOM: probe `el.shadowRoot` and drive it there.

## File uploads

`browser_file_upload` with the absolute path, after clicking the control that opens the chooser
(or set it directly on the `input[type=file]`). Files must be in a plain local folder (not a
cloud-synced symlink): copy to `output/uploads/` inside the kit first if the upload is refused.
Verify the file name appears on the page, and on UltiPro that its include-checkbox is checked.

## What is never Claude's click

Attestation and certification checkboxes ("I certify the above is true"), consent to terms,
voluntary self-identification (veteran, disability, gender, ethnicity), passwords, two-factor
codes, and Submit. Pre-fill everything else, keep the window open, and list those controls in
order for the applicant.

## Before you call a form done

Walk every page, not just the fields you filled. Open every optional section and decide after
looking. Anything the site auto-filled is a claim in the applicant's name: enumerate those
controls and decode opaque values before accepting them. A form with no validation errors is not
a verified form.

## After a submit

On at least one ATS (UltiPro) the application freezes but the candidate profile stays editable,
so a field missed at submit time can still be fixed there. Check before calling a gap permanent.
Append what you learn about a new host to `references/site-notes.md`.
