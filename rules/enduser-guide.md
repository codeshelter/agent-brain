# End-user guide writing rules (customer-facing .docx guides, all projects)

**Reference baseline:** *REST-API User Guide for Sphere HSM v6.6.2, Edition 02.08*
(17/09/2026), approved by the owner. When a rule below is unclear, do what 02.08 does.
These rules apply to every edit of a customer guide, not only to cleanup passes.

## 1. What a reader needs
The reader is mid-task, looking something up. Every section answers "what do I do, and
what will I see". Comprehensive means **all the facts are there**, not that sentences are long.

## 2. Voice and wording
- **No em dashes or en dashes** (02.08 has zero). Use a full stop, a comma or parentheses.
- **Cut hard.** Remove fluff, statements of the obvious and repeated introductions.
  A cleanup pass targets **30-40% off the prose**.
- **Short, direct sentences in the second person / imperative:** "Set the HSM proxy
  address before using any HSM operation."
- Keep a human voice, but brevity and direct action win.
- Paragraphs over ~80 words get split at their seams; a comma-series of 4+ items becomes a bullet list.

## 3. Cut words, never facts
Never delete, whatever the word target says:
- **Reference tables and their rows** (settings, endpoints, OIDs, verdicts, troubleshooting).
  Trimming a table's lead-in sentence is fine; deleting rows is not.
- **Exact commands, config samples, numeric identifiers** and **typed confirmation words**
  (e.g. APPLY, TRUST, CREATE, MIGRATE, REVERT, STOP, UNVERIFIED, UPLOAD, ROLLBACK, RESTORE).
- **Documented gotchas and honest limitations** ("poll-only, no traps", "no user name or
  password as delivered"). They read like hedging and are exactly what a word-count pass
  deletes, yet they are the only thing stopping a reader assuming a capability that is not there.

When brevity and accuracy pull apart, **accuracy wins and the trade is reported**.
**Measure prose separately** from tables, code/config listings, headings, captions and the
TOC. Quote any percentage against prose only, and say so.

## 4. Structure (as in 02.08)
- Built-in **Heading 1-4 only**, auto-numbered (never type numbers into heading text).
  Heading 1 in CAPITALS (INTRODUCTION, REST API DEPLOYMENT, ...); Heading 2-4 in Title Case.
  No deeper than level 4.
- Front matter: title page, **Document history** table, auto **Table of Contents** (a field,
  refreshed after every structural edit).
- A task section reads in this order:
  1. **One purpose sentence** (Body Text): what this achieves and when to do it.
  2. **Steps**: commands in the `Code Block` style, one line per paragraph; each step's
     action in **bold** when it is a bullet instruction.
  3. **Placeholder definitions** straight after the block that uses them.
  4. **Expected result / how to verify.**
  5. At most one or two **`Note:`** paragraphs for gotchas, limits or safety.
- **Notes** use the `note` style and start with `Note:` or `Note (context):`. No Warning,
  Caution or Tip styles (02.08 uses none). A note states a consequence, not advice fluff.
- **Tables**: 2-3 columns, bold header row, `Table Grid`. Use them for reference data
  (endpoints, settings, credentials pointers, tools), never for layout.
- **Figures**: never inside a table cell. `Caption` style below the figure with a
  `SEQ Figure` field; the figure paragraph is kept with its caption.
- **Lists**: `Bullet 1` / `List Bullet`.

## 5. Values, placeholders and screenshots
- Environment-specific values are **placeholders in angle brackets, UPPER_SNAKE**:
  `<APPLIANCE_IP>`, `<PROXY_ENV_ADDRESS>`, each defined right after first use.
- **Never a real internal host, IP, user or password** in a customer guide, not even as
  "for example". Example addresses use the documentation range (192.0.2.x).
- **Credentials** are never printed. Write "see the delivery / customer handoff".
- **Screenshots are sanitised captures:** build SHA, branch and CI values become
  `<build>`, `<branch>`, `<ci>`. Re-capture from the shipping build when the UI changes.
- Paths, unit names and file names must be **verified against the product source**, not
  assumed (e.g. a service unit and its binary can have different names).

## 6. Editions and files
- The version in the file name is the **product release** (`v6.6.2`); the document
  revision is **`Edition NN.NN`**.
- File name: `<Guide title> for <Product> v<release> Edition NN.NN.docx`.
- **Never overwrite an issued or reviewed edition.** A change = new edition, new file;
  earlier editions stay untouched on disk.
- Add a **Document history** row: `Edition / Version | Date (DD/MM/YYYY) | Description`.
  The description is one or two sentences, starts with a verb, and names the sections
  touched ("Remove section 4.3.12.4 ...", "Add the service unit status dashboard to 4.3.13 ...").
- Cover and footer show edition/date through `REF DOC_EDITION` / `REF DOC_LAST_UPDATE`
  fields whose bookmarks live in the **last history row**. Move the bookmarks to the new
  row; never edit the displayed text.
- Keep the template's classification marking; re-label before any external distribution.

## 7. Every edit also checks for defects
An editorial pass surfaces product and document defects. On every edit:
- grep for **pre-rename names/paths** (e.g. old product prefixes in paths, users, units);
- check **cross-references** resolve (no dangling "see section X");
- look for **procedure vs screenshot contradictions**;
- remove **reviewer notes left in body text**;
- report **fact changes separately from word changes**.

## 8. Tooling (Windows)
- Build/restructure with **python-docx** (move elements with `addprevious`/`addnext`,
  anchors found by (style, text prefix), never by paragraph index).
- Use **Word COM only to refresh**: `Fields.Update()`, `TablesOfContents(i).Update()`,
  `Repaginate()`, `SaveAs2(new_path, 16)`. Pass COM arguments **positionally**.
- **RMS-protected** source: `Permission.Enabled = False`, then `SaveAs2` to a new file.
- Fix the `Body Text` **contextualSpacing** inheritance (otherwise consecutive paragraphs
  set as one wall); do not apply that fix to `Normal` or `Code Block`.
- Read 1-column tables raw (their content may contain `|`); never `.strip()` code lines.
- Full recipes: the Balto memory topic `reference_word_docx_editing_via_com.md`.

## 9. Definition of done for a new edition
- [ ] New file with the next Edition number; previous edition byte-identical.
- [ ] Document history row added, edition/date bookmarks moved, fields + TOC refreshed.
- [ ] 0 em/en dashes, 0 figures in tables, 0 dangling cross-references, 0 reviewer notes.
- [ ] 0 real hosts/IPs/credentials; screenshots sanitised.
- [ ] Prose-only word count before/after reported; tables, commands, gotchas intact.
- [ ] Rendered to PDF and page images checked (layout, captions with figures).
- [ ] Fact changes and discovered product defects reported separately to the owner.
