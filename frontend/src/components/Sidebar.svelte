<script lang="ts">
  import { onMount, tick } from 'svelte'
  import { SvelteSet } from 'svelte/reactivity'

  import NavIcon from './NavIcon.svelte'
  import { folderOf } from '../lib/newNote'
  import { interceptClick, routeHref, type Route } from '../lib/router'
  import {
    buildTree,
    childKey,
    folderNamesIn,
    folderTargets,
    parentOf,
    renameFolderPrefix,
    validateFolderName,
    type NoteTree,
    type Outcome,
    type TreeNode,
  } from '../lib/tree'
  import type { Note } from '../lib/types'

  /**
   * KAN-554's sidebar: a folder tree over the `path` column. **Tree-only since KAN-1996**; the flat
   * list survives only as how a search renders (KAN-962), because relevance is an order and the tree
   * has nowhere to put one. The tree is a *view* of paths (`lib/tree.ts`), and `countNotes` asserts
   * mechanically that it never hides a note.
   *
   * **KAY-168 makes it a place to organise.** Every row has a `...` menu (Move to, Rename; for a
   * folder, New note here, New subfolder, Rename folder). The menu is the keyboard and touch path;
   * drag-and-drop onto a folder is the pointer shortcut and is switched off on coarse pointers so it
   * never fights scrolling. F2 or a double-click renames in place. A new folder is a client-only
   * placeholder (ADR 0008 amendment): `App` holds it, nothing is sent to the server, and it is a
   * real folder only once a note's path says so.
   *
   * Everything structural is decided in `lib/tree.ts`; the writes are `App`'s (so a `401` reaches its
   * `discard()`), and this component only asks and announces the answer (ADR 0004: presentation).
   */
  const {
    notes,
    route,
    loading,
    query = '',
    placeholders = [],
    contextFolder = '',
    onsearch = () => {},
    oncreate = () => {},
    onfolder = () => {},
    onmove = async () => ({ ok: false, message: '' }),
    onrenamenote = async () => ({ ok: false, message: '' }),
    onrenamefolder = async () => ({ ok: false, message: '' }),
    onnewfolder = () => {},
  }: {
    notes: Note[]
    route: Route
    loading: boolean
    /** The **committed** search term — what the last search actually asked for, `''` for none. */
    query?: string
    /** Client-only empty folders (full paths), owned by `App`. */
    placeholders?: string[]
    /** The "current folder" for a new note or folder, `''` for the top level. */
    contextFolder?: string
    /** Fired with the trimmed term on submit, and with `''` when the search is cleared. */
    onsearch?: (term: string) => void
    /** KAY-166's "New note", optionally in a folder (the row menu's "New note here"). */
    oncreate?: (folder?: string) => void
    /** A folder row was clicked: its full path, the "current folder" for the next new note. */
    onfolder?: (key: string) => void
    /** Move a note into `folder` (`''` is the top level): one `PATCH` to `path`. */
    onmove?: (note: Note, folder: string) => Promise<Outcome>
    /** Rename a note's title. */
    onrenamenote?: (note: Note, title: string) => Promise<Outcome>
    /** Rename (or move) a folder: `POST /notes/move-folder`, or local for a placeholder. */
    onrenamefolder?: (from: string, to: string) => Promise<Outcome>
    /** A validated new folder path; `App` records it as a placeholder. */
    onnewfolder?: (folder: string) => void
  } = $props()

  /**
   * The input's own text, kept apart from `query` on purpose (KAN-559): `query` is App's — what
   * drove the request that produced `notes` — and this is what is typed but not yet submitted. A
   * writable `$derived`: reassigning it is the draft while typing, until `query` changes again.
   */
  let draft = $derived(query)

  function submit(event: SubmitEvent): void {
    event.preventDefault()
    onsearch(draft.trim())
  }

  function clear(): void {
    draft = ''
    onsearch('')
  }

  /** Whether `notes` is a *result set* rather than the corpus. `query` is the committed term. */
  const searching = $derived(query !== '')

  const tree: NoteTree = $derived(buildTree(notes, placeholders))
  const targets: string[] = $derived(folderTargets(notes, placeholders))

  /**
   * Which folders are open, as the set of folders explicitly **closed** (keyed by folder path).
   * Inverted on purpose: the default has to be "expanded", and a folder that appears later is open.
   * A folder rename carries its keys across (`renameFolderPrefix`).
   */
  const closed = new SvelteSet<string>()

  function toggle(key: string): void {
    if (!closed.delete(key)) {
      closed.add(key)
    }
  }

  function isOpen(note: Note): boolean {
    return route.name === 'note' && route.ref === note.ref
  }

  /** The row's left inset, clamped past the eighth level (a title you can read beats a position). */
  function inset(depth: number): string {
    return `${0.5 + Math.min(depth, 8) * 0.7}rem`
  }

  /** `title` when there is one, so a row is never a blank line. `''` is a legal title server-side. */
  function label(note: Note): string {
    return note.title === '' ? note.ref : note.title
  }

  function lastSegment(key: string): string {
    return key.slice(key.lastIndexOf('/') + 1)
  }

  // ---- announcements -----------------------------------------------------------------------

  let toast: { text: string; ok: boolean } | null = $state(null)
  let toastTimer: ReturnType<typeof setTimeout> | undefined
  /** Polite, for drag-over: "Drop to move into X". Separate from the toast so it never lingers. */
  let dragNotice = $state('')

  function announce(outcome: Outcome | { ok: boolean; message: string }): void {
    clearTimeout(toastTimer)
    if (outcome.message === '') {
      toast = null
      return
    }
    toast = { text: outcome.message, ok: outcome.ok }
    toastTimer = setTimeout(() => (toast = null), outcome.ok ? 7000 : 12000)
  }

  // ---- pointer capability --------------------------------------------------------------------

  /** Coarse pointers (touch) use the menu only: HTML5 drag there fights scrolling. */
  let coarse = $state(false)

  onMount(() => {
    let watched: MediaQueryList | null
    try {
      watched = typeof window.matchMedia === 'function' ? window.matchMedia('(pointer: coarse)') : null
    } catch {
      watched = null // a test double that only understands width queries
    }
    const update = (): void => {
      coarse = watched?.matches ?? false
    }
    update()
    watched?.addEventListener?.('change', update)
    return () => {
      watched?.removeEventListener?.('change', update)
      clearTimeout(toastTimer)
    }
  })

  // ---- the row menu --------------------------------------------------------------------------

  interface MenuState {
    kind: 'note' | 'folder'
    /** The note's ref, or the folder's key. */
    id: string
    view: 'main' | 'move'
    left: number
    top: number
  }

  interface MenuEntry {
    label: string
    keepOpen?: boolean
    run: () => void
  }

  let menu = $state<MenuState | null>(null)
  let menuEl: HTMLDivElement | undefined = $state()
  let navEl: HTMLElement | undefined = $state()

  const menuNote = $derived(menu?.kind === 'note' ? notes.find((found) => found.ref === menu?.id) : undefined)

  const menuEntries: MenuEntry[] = $derived.by(() => {
    if (menu === null) {
      return []
    }
    if (menu.kind === 'folder') {
      const key = menu.id
      return [
        { label: 'New note here', run: () => createIn(key) },
        { label: 'New subfolder', run: () => startCreateFolder(key) },
        { label: 'Rename folder', run: () => startRename('folder', key) },
      ]
    }
    const target = menuNote
    if (target === undefined) {
      return []
    }
    if (menu.view === 'main') {
      return [
        { label: 'Move to…', keepOpen: true, run: () => showMoveTargets() },
        { label: 'Rename', run: () => startRename('note', target.ref) },
      ]
    }
    const here = folderOf(target.path)
    const entries: MenuEntry[] = []
    if (here !== '' || target.path === '') {
      entries.push({ label: 'Unfiled (top level)', run: () => void runMove(target, '') })
    }
    for (const folder of targets) {
      if (folder !== here) {
        entries.push({ label: folder, run: () => void runMove(target, folder) })
      }
    }
    return entries
  })

  const menuHeading = $derived(
    menu?.kind === 'note' && menu.view === 'move' ? 'Move to…' : menu?.kind === 'folder' ? 'Folder' : 'Note',
  )

  function rowEl(kind: 'note' | 'folder', id: string): HTMLElement | null {
    return (
      Array.from(navEl?.querySelectorAll<HTMLElement>('[data-row]') ?? []).find(
        (el) => el.dataset.row === kind && el.dataset.id === id,
      ) ?? null
    )
  }

  async function focusRow(kind: 'note' | 'folder', id: string): Promise<void> {
    await tick()
    rowEl(kind, id)?.focus()
  }

  function placeMenu(anchor: HTMLElement): void {
    if (menu === null || menuEl === undefined) {
      return
    }
    const rect = anchor.getBoundingClientRect()
    const width = menuEl.offsetWidth
    const height = menuEl.offsetHeight
    const left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8))
    let top = rect.bottom + 4
    if (top + height > window.innerHeight - 8) {
      top = Math.max(8, rect.top - height - 4)
    }
    menu.left = left
    menu.top = top
  }

  function focusMenuItem(index: number): void {
    const items = menuEl?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []
    if (items.length === 0) {
      return
    }
    items[((index % items.length) + items.length) % items.length].focus()
  }

  async function openMenu(kind: 'note' | 'folder', id: string, anchor: HTMLElement): Promise<void> {
    if (menu !== null && menu.kind === kind && menu.id === id) {
      closeMenu(true)
      return
    }
    const rect = anchor.getBoundingClientRect()
    menu = { kind, id, view: 'main', left: rect.left, top: rect.bottom + 4 }
    await tick()
    placeMenu(anchor)
    focusMenuItem(0)
  }

  function closeMenu(returnFocus: boolean): void {
    const open = menu
    menu = null
    if (returnFocus && open !== null) {
      void focusRow(open.kind, open.id)
    }
  }

  async function showMoveTargets(): Promise<void> {
    if (menu === null) {
      return
    }
    const anchor = menuAnchor()
    menu.view = 'move'
    await tick()
    if (anchor !== null) {
      placeMenu(anchor)
    }
    focusMenuItem(0)
  }

  /** The `...` button of the row the menu belongs to, for placement. */
  function menuAnchor(): HTMLElement | null {
    if (menu === null) {
      return null
    }
    return rowEl(menu.kind, menu.id)?.closest('li')?.querySelector<HTMLElement>(':scope > .more') ?? null
  }

  function choose(entry: MenuEntry): void {
    if (!entry.keepOpen) {
      menu = null
    }
    entry.run()
  }

  function menuKeydown(event: KeyboardEvent): void {
    const items = Array.from(menuEl?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])
    const at = items.indexOf(document.activeElement as HTMLElement)
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        focusMenuItem(at + 1)
        break
      case 'ArrowUp':
        event.preventDefault()
        focusMenuItem(at === -1 ? -1 : at - 1)
        break
      case 'Home':
        event.preventDefault()
        focusMenuItem(0)
        break
      case 'End':
        event.preventDefault()
        focusMenuItem(-1)
        break
      case 'Escape':
        event.preventDefault()
        event.stopPropagation()
        closeMenu(true)
        break
      case 'Tab':
        closeMenu(true)
        break
    }
  }

  /** Outside click closes without stealing focus; a scroll or resize would strand a fixed menu. */
  $effect(() => {
    if (menu === null) {
      return
    }
    const outside = (event: PointerEvent): void => {
      const target = event.target as Node | null
      if (target !== null && menuEl?.contains(target)) {
        return
      }
      if (target instanceof Element && target.closest('.more') !== null) {
        return // the trigger's own click toggles
      }
      closeMenu(false)
    }
    const dismiss = (): void => closeMenu(false)
    window.addEventListener('pointerdown', outside, true)
    window.addEventListener('scroll', dismiss, true)
    window.addEventListener('resize', dismiss)
    return () => {
      window.removeEventListener('pointerdown', outside, true)
      window.removeEventListener('scroll', dismiss, true)
      window.removeEventListener('resize', dismiss)
    }
  })

  // ---- move ----------------------------------------------------------------------------------

  async function runMove(target: Note, folder: string): Promise<void> {
    const outcome = await onmove(target, folder)
    announce(outcome)
    if (outcome.ok) {
      closed.delete(folder)
      void focusRow('note', target.ref)
    }
  }

  let dragRef: string | null = $state(null)
  /** The folder key being dragged over; `''` is the top level; `null` is none. */
  let dropKey: string | null = $state(null)

  function dragStart(event: DragEvent, note: Note): void {
    dragRef = note.ref
    if (event.dataTransfer !== null) {
      event.dataTransfer.effectAllowed = 'move'
      event.dataTransfer.setData('text/plain', note.ref)
    }
  }

  function dragEnd(): void {
    dragRef = null
    dropKey = null
    dragNotice = ''
  }

  function dragOver(event: DragEvent, folder: string): void {
    if (dragRef === null) {
      return
    }
    event.preventDefault()
    if (event.dataTransfer !== null) {
      event.dataTransfer.dropEffect = 'move'
    }
    if (dropKey !== folder) {
      dropKey = folder
      dragNotice = folder === '' ? 'Drop to move to the top level.' : `Drop to move into ${folder}.`
    }
  }

  function dragLeave(folder: string): void {
    if (dropKey === folder) {
      dropKey = null
    }
  }

  function drop(event: DragEvent, folder: string): void {
    if (dragRef === null) {
      return
    }
    event.preventDefault()
    const target = notes.find((found) => found.ref === dragRef)
    dragEnd()
    if (target !== undefined) {
      void runMove(target, folder)
    }
  }

  // ---- inline rename -------------------------------------------------------------------------

  let renaming: { kind: 'note' | 'folder'; id: string } | null = $state(null)
  let renameError = $state('')
  let renameDone = false

  function startRename(kind: 'note' | 'folder', id: string): void {
    renameDone = false
    renameError = ''
    renaming = { kind, id }
  }

  /** Focuses and selects the field the moment it exists. */
  function focusSelect(node: HTMLInputElement): void {
    node.focus()
    node.select()
  }

  function cancelRename(): void {
    const was = renaming
    renameDone = true
    renaming = null
    renameError = ''
    if (was !== null) {
      void focusRow(was.kind, was.id)
    }
  }

  async function commitRename(value: string, viaBlur: boolean): Promise<void> {
    const current = renaming
    if (current === null || renameDone) {
      return
    }
    if (current.kind === 'note') {
      const target = notes.find((found) => found.ref === current.id)
      const title = value.trim()
      if (target === undefined || title === target.title) {
        cancelRename()
        return
      }
      if (title === '') {
        if (viaBlur) {
          cancelRename()
        } else {
          renameError = 'A note needs a title.'
        }
        return
      }
      renameDone = true
      renaming = null
      const outcome = await onrenamenote(target, title)
      announce(outcome)
      void focusRow('note', current.id)
      return
    }

    const from = current.id
    const name = lastSegment(from)
    if (value.trim() === name) {
      cancelRename()
      return
    }
    const siblings = folderNamesIn(tree, parentOf(from)).filter((sibling) => sibling !== name)
    const checked = validateFolderName(value, siblings)
    if (!checked.ok) {
      if (viaBlur) {
        cancelRename()
        if (value.trim() !== '') {
          announce({ ok: false, message: checked.error })
        }
      } else {
        renameError = checked.error
      }
      return
    }
    renameDone = true
    renaming = null
    const to = childKey(parentOf(from), checked.name)
    const outcome = await onrenamefolder(from, to)
    if (outcome.ok) {
      for (const key of [...closed]) {
        const next = renameFolderPrefix(key, from, to, false)
        if (next !== null && next !== key) {
          closed.delete(key)
          closed.add(next)
        }
      }
      const context = renameFolderPrefix(contextFolder, from, to, false)
      if (context !== null) {
        onfolder(context)
      }
    }
    announce(outcome)
    void focusRow('folder', outcome.ok ? to : from)
  }

  // ---- new folder (a client-only placeholder) --------------------------------------------------

  let creating: { parent: string } | null = $state(null)
  let createError = $state('')
  let createDone = false

  function startCreateFolder(parent: string): void {
    const there = parent !== '' && targets.includes(parent) ? parent : ''
    // Open the folder and every ancestor so the editable row is visible.
    let prefix = ''
    for (const segment of there.split('/').filter((part) => part !== '')) {
      prefix = prefix === '' ? segment : `${prefix}/${segment}`
      closed.delete(prefix)
    }
    createDone = false
    createError = ''
    creating = { parent: there }
  }

  function cancelCreate(): void {
    createDone = true
    creating = null
    createError = ''
  }

  function commitCreate(value: string, viaBlur: boolean): void {
    const current = creating
    if (current === null || createDone) {
      return
    }
    if (viaBlur && value.trim() === '') {
      cancelCreate()
      return
    }
    const checked = validateFolderName(value, folderNamesIn(tree, current.parent))
    if (!checked.ok) {
      if (viaBlur) {
        cancelCreate()
        announce({ ok: false, message: checked.error })
      } else {
        createError = checked.error
      }
      return
    }
    createDone = true
    creating = null
    const key = childKey(current.parent, checked.name)
    onnewfolder(key)
    closed.delete(key)
    onfolder(key)
    announce({
      ok: true,
      message: `Folder "${checked.name}" created. It lives only in this tab: it stays until a note is placed in it, and disappears on reload if empty.`,
    })
    void focusRow('folder', key)
  }

  /** "New note here": the folder becomes current, then the same instant create as the button. */
  function createIn(folder: string): void {
    onfolder(folder)
    oncreate(folder)
  }

  // ---- keyboard ------------------------------------------------------------------------------

  /**
   * `N` creates a note (KAY-166), F2 renames the focused row, the context-menu key or Shift+F10 opens
   * its menu. Never from a text field: the search box and the rename input must keep their keys.
   */
  function treeKeydown(event: KeyboardEvent): void {
    const target = event.target as HTMLElement | null
    if (target?.closest('input, textarea, select, [contenteditable]')) {
      return
    }
    const row = target?.closest<HTMLElement>('[data-row]') ?? null
    if (row !== null) {
      const kind = row.dataset.row as 'note' | 'folder'
      const id = row.dataset.id ?? ''
      if (event.key === 'F2') {
        event.preventDefault()
        startRename(kind, id)
        return
      }
      if (event.key === 'ContextMenu' || (event.key === 'F10' && event.shiftKey)) {
        const anchor = row.closest('li')?.querySelector<HTMLElement>(':scope > .more')
        if (anchor) {
          event.preventDefault()
          void openMenu(kind, id, anchor)
        }
        return
      }
    }
    if (event.key.toLowerCase() !== 'n' || event.ctrlKey || event.metaKey || event.altKey) {
      return
    }
    event.preventDefault()
    oncreate()
  }
</script>

{#snippet editField(initial: string, name: string, error: string, commit: (value: string, viaBlur: boolean) => void, cancel: () => void)}
  <span class="edit-wrap">
    <input
      class="rename"
      type="text"
      value={initial}
      aria-label={name}
      aria-invalid={error !== ''}
      use:focusSelect
      onkeydown={(event) => {
        const input = event.target as HTMLInputElement
        if (event.key === 'Enter') {
          event.preventDefault()
          commit(input.value, false)
        } else if (event.key === 'Escape') {
          event.preventDefault()
          cancel()
        }
      }}
      onblur={(event) => commit((event.target as HTMLInputElement).value, true)}
    />
    {#if error !== ''}
      <span class="edit-error" role="alert">{error}</span>
    {/if}
  </span>
{/snippet}

{#snippet moreButton(kind: 'note' | 'folder', id: string, name: string)}
  <button
    type="button"
    class="more"
    tabindex="-1"
    aria-label="Actions for {name}"
    aria-haspopup="menu"
    aria-expanded={menu?.kind === kind && menu.id === id}
    data-testid="row-menu-button"
    onclick={(event) => void openMenu(kind, id, event.currentTarget)}
  >
    <NavIcon name="more" size={20} />
  </button>
{/snippet}

{#snippet noteRow(note: Note, secondary: string, depth: number)}
  <li class="item" class:dragging={dragRef === note.ref}>
    {#if renaming?.kind === 'note' && renaming.id === note.ref}
      <div class="row note editing" style:padding-left={inset(depth)}>
        {@render editField(note.title, `Rename ${label(note)}`, renameError, commitRename, cancelRename)}
      </div>
    {:else}
      <a
        href={routeHref({ name: 'note', ref: note.ref })}
        class="row note"
        class:open={isOpen(note)}
        aria-current={isOpen(note) ? 'page' : undefined}
        style:padding-left={inset(depth)}
        data-row="note"
        data-id={note.ref}
        draggable={!coarse && !searching && !loading}
        ondragstart={(event) => dragStart(event, note)}
        ondragend={dragEnd}
        ondblclick={() => startRename('note', note.ref)}
        onclick={(event) => interceptClick(event, `/notes/${note.ref}`)}
      >
        <span class="title">{label(note)}</span>
        <span class="sub">{secondary}</span>
      </a>
    {/if}
    {@render moreButton('note', note.ref, label(note))}
  </li>
{/snippet}

{#snippet createRow(depth: number)}
  <li class="item">
    <div class="row folder editing" style:padding-left={inset(depth)}>
      <span class="twist" aria-hidden="true">▸</span>
      {@render editField('New folder', 'New folder name', createError, commitCreate, cancelCreate)}
    </div>
  </li>
{/snippet}

{#snippet branch(node: TreeNode, depth: number)}
  {#if node.kind === 'folder'}
    <li class="item">
      {#if renaming?.kind === 'folder' && renaming.id === node.key}
        <div class="row folder editing" style:padding-left={inset(depth)}>
          <span class="twist" aria-hidden="true">{closed.has(node.key) ? '▸' : '▾'}</span>
          {@render editField(node.name, `Rename folder ${node.name}`, renameError, commitRename, cancelRename)}
        </div>
      {:else}
        <button
          type="button"
          class="row folder"
          class:drop={dropKey === node.key}
          style:padding-left={inset(depth)}
          aria-expanded={!closed.has(node.key)}
          data-row="folder"
          data-id={node.key}
          ondragover={(event) => dragOver(event, node.key)}
          ondragleave={() => dragLeave(node.key)}
          ondrop={(event) => drop(event, node.key)}
          ondblclick={() => startRename('folder', node.key)}
          onclick={() => {
            toggle(node.key)
            onfolder(node.key)
          }}
        >
          <span class="twist" aria-hidden="true">{closed.has(node.key) ? '▸' : '▾'}</span>
          <span class="title">{node.name}</span>
        </button>
      {/if}
      {@render moreButton('folder', node.key, node.name)}
      {#if !closed.has(node.key)}
        <ul>
          {#if creating?.parent === node.key}
            {@render createRow(depth + 1)}
          {/if}
          {#each node.children as child (child.kind === 'folder' ? `d:${child.key}` : `n:${child.note.ref}`)}
            {@render branch(child, depth + 1)}
          {/each}
          {#if node.children.length === 0 && creating?.parent !== node.key}
            <li
              class="hint"
              class:drop={dropKey === node.key}
              style:padding-left={inset(depth + 1)}
              ondragover={(event) => dragOver(event, node.key)}
              ondragleave={() => dragLeave(node.key)}
              ondrop={(event) => drop(event, node.key)}
            >
              Empty. Drag a note here, or create one.
            </li>
          {/if}
        </ul>
      {/if}
    </li>
  {:else}
    <!-- The filename, because the folder rows above already say the rest of the path. -->
    {@render noteRow(node.note, node.filename, depth)}
  {/if}
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<nav class="sidebar" aria-label="Notes" bind:this={navEl} onkeydown={treeKeydown}>
  <!-- KAY-166: a tonal button; the note is created immediately, see `oncreate`. KAY-168 adds the
       new-folder button beside it. -->
  <div class="create">
    <button type="button" class="new-note" onclick={() => oncreate()} data-testid="new-note-button">
      <NavIcon name="add" size={20} />
      New note
    </button>
    <button
      type="button"
      class="new-folder"
      aria-label="New folder"
      title="New folder"
      disabled={searching}
      onclick={() => startCreateFolder(contextFolder)}
      data-testid="new-folder-button"
    >
      <NavIcon name="new-folder" size={22} />
    </button>
  </div>

  <!--
    KAN-559's search box. `--q` on the client is one flag and one input here, and it stays that
    shape: submitting sends `draft.trim()` up to `onsearch`, which is App's request to make.
  -->
  <form class="search" onsubmit={submit} data-testid="search-form">
    <input
      type="search"
      class="search-input"
      placeholder="Search notes…"
      bind:value={draft}
      aria-label="Search notes"
      data-testid="search-input"
    />
    {#if query !== ''}
      <button type="button" class="clear-search" onclick={clear} data-testid="clear-search">
        Clear
      </button>
    {/if}
  </form>

  {#if searching}
    <p class="ordering" data-testid="search-ordering">Matches, best first. Ordered by relevance, not grouped by folder.</p>
  {/if}

  {#if loading}
    <p class="empty">Loading…</p>
  {:else if notes.length === 0 && placeholders.length === 0 && creating === null}
    <p class="empty">{query === '' ? 'No notes yet. Create one, or ask your agent to.' : `No notes match "${query}".`}</p>
  {:else if searching}
    <!-- Every note, in the order the API returned them (`ts_rank DESC, id DESC`), nothing grouped. -->
    <ul data-testid="note-list">
      {#each notes as note (note.ref)}
        {@render noteRow(note, note.path === '' ? '—' : note.path, 0)}
      {/each}
    </ul>
  {:else}
    <ul data-testid="note-tree">
      {#if creating?.parent === ''}
        {@render createRow(0)}
      {/if}
      {#each tree.roots as node (node.kind === 'folder' ? `d:${node.key}` : `n:${node.note.ref}`)}
        {@render branch(node, 0)}
      {/each}
    </ul>

    {#if tree.unpathed.length > 0}
      <!--
        Notes with no path, under a label that names the **absence** of one (`lib/tree.ts` explains
        why they are a separate field). The heading is also a drop target for "top level".
      -->
      <section class="unpathed" data-testid="unpathed" aria-label="Notes with no path">
        <h3
          class:drop={dropKey === ''}
          ondragover={(event) => dragOver(event, '')}
          ondragleave={() => dragLeave('')}
          ondrop={(event) => drop(event, '')}
        >
          no path <span class="count">{tree.unpathed.length}</span>
        </h3>
        <ul>
          {#each tree.unpathed as note (note.ref)}
            {@render noteRow(note, note.ref, 0)}
          {/each}
        </ul>
      </section>
    {/if}

    {#if dragRef !== null}
      <!-- A dock at the end of the list while dragging: it adds no height above the dragged row. -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="root-drop"
        class:drop={dropKey === ''}
        data-testid="root-drop"
        ondragover={(event) => dragOver(event, '')}
        ondragleave={() => dragLeave('')}
        ondrop={(event) => drop(event, '')}
      >
        Unfiled (top level)
      </div>
    {/if}
  {/if}

  {#if menu !== null}
    <div
      class="menu"
      role="menu"
      aria-label={menuHeading}
      tabindex="-1"
      bind:this={menuEl}
      style:left="{menu.left}px"
      style:top="{menu.top}px"
      onkeydown={menuKeydown}
      data-testid="row-menu"
    >
      {#if menu.view === 'move'}
        <div class="menu-heading" aria-hidden="true">Move to…</div>
      {/if}
      {#each menuEntries as entry (entry.label)}
        <button type="button" role="menuitem" class="menu-item" tabindex="-1" onclick={() => choose(entry)}>
          {entry.label}
        </button>
      {:else}
        <div class="menu-heading">No other folders.</div>
      {/each}
    </div>
  {/if}

  <div class="live" aria-live="polite" aria-atomic="true">{dragNotice}</div>
  <div class="toast-region" aria-live="polite">
    {#if toast !== null}
      <div class="toast" class:bad={!toast.ok} role={toast.ok ? 'status' : 'alert'} data-testid="tree-toast">
        <span>{toast.text}</span>
        <button type="button" class="toast-close" aria-label="Dismiss" onclick={() => (toast = null)}>×</button>
      </div>
    {/if}
  </div>
</nav>

<style>
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    min-width: 0;
    overflow-y: auto;
    padding: 1rem 0.5rem 1.5rem;
    background: var(--surface-container);
    border-right: 1px solid var(--outline-variant);
  }

  .create {
    display: flex;
    gap: 0.4rem;
    padding: 0 0.5rem;
  }

  .new-note {
    display: inline-flex;
    flex: 1;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    min-width: 0;
    padding: 0.65rem 1rem;
    border: 0;
    border-radius: var(--shape-full);
    background: var(--secondary-container);
    color: var(--on-secondary-container);
    cursor: pointer;
    font: inherit;
    font-size: var(--type-body-medium-size);
    font-weight: 500;
  }

  .new-folder {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: 2.75rem;
    border: 0;
    border-radius: var(--shape-full);
    background: var(--secondary-container);
    color: var(--on-secondary-container);
    cursor: pointer;
  }

  .new-folder:disabled {
    cursor: default;
    opacity: 0.38;
  }

  .new-note:hover,
  .new-folder:hover:not(:disabled) {
    background: color-mix(in srgb, var(--on-secondary-container) calc(var(--state-hover) * 100%), var(--secondary-container));
  }

  .new-note:focus-visible,
  .new-folder:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
  }

  .search {
    display: flex;
    gap: 0.3rem;
    padding: 0 0.5rem;
  }

  .search-input {
    flex: 1;
    min-width: 0;
    padding: 0.3rem 0.5rem;
    border: 1px solid var(--outline);
    border-radius: var(--shape-full);
    background: transparent;
    color: inherit;
    font: inherit;
    font-size: var(--type-body-medium-size);
  }

  .clear-search {
    flex: none;
    padding: 0.2rem 0.5rem;
    border: 1px solid var(--outline);
    border-radius: var(--shape-full);
    background: transparent;
    color: var(--on-surface-variant);
    cursor: pointer;
    font: inherit;
    font-size: var(--type-label-medium-size);
  }

  .ordering {
    margin: 0;
    padding: 0 0.5rem;
    color: var(--on-surface-variant);
    font-size: var(--type-label-medium-size);
    line-height: 1.35;
  }

  ul {
    margin: 0;
    /* The indent is on the row, not on the list: see `inset()` on why it has to be clampable. */
    padding: 0;
    list-style: none;
  }

  .item {
    position: relative;
  }

  .row {
    display: block;
    width: 100%;
    min-width: 0;
    padding: 0.3rem 2.4rem 0.3rem 0.5rem;
    border: 0;
    border-radius: var(--shape-md);
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    text-decoration: none;
  }

  .row:hover {
    background: var(--layer-hover);
  }

  .row.folder {
    display: flex;
    align-items: baseline;
    gap: 0.35rem;
    color: var(--on-surface-variant);
    cursor: pointer;
    font-size: var(--type-body-medium-size);
  }

  .row.drop,
  .hint.drop,
  .unpathed h3.drop,
  .root-drop.drop {
    background: var(--primary-container);
    color: var(--on-primary-container);
    outline: 2px dashed var(--primary);
    outline-offset: -2px;
  }

  .item.dragging > .row {
    opacity: 0.5;
  }

  .twist {
    flex: none;
    font-size: var(--type-label-small-size);
  }

  a.row.open {
    background: var(--secondary-container);
    color: var(--on-secondary-container);
  }

  .row:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: -2px;
  }

  .title {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sub {
    display: block;
    overflow: hidden;
    color: var(--on-surface-variant);
    font-family: var(--mono);
    font-size: var(--type-label-medium-size);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* The row's `...` button: a sibling of the row (a link cannot hold a button), shown on hover or
     focus for a pointer and always for touch. */
  .more {
    position: absolute;
    top: 0.15rem;
    right: 0.25rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    padding: 0;
    border: 0;
    border-radius: var(--shape-full);
    background: transparent;
    color: var(--on-surface-variant);
    cursor: pointer;
    opacity: 0;
  }

  /* The folder row is followed by its children's list, so the button sits on the row's own line. */
  .row:hover + .more,
  .row:focus-visible + .more,
  .more:hover,
  .more[aria-expanded='true'],
  .more:focus-visible {
    opacity: 1;
  }

  .more:hover {
    background: var(--layer-hover);
  }

  .more:focus-visible {
    outline: 2px solid var(--primary);
  }

  @media (hover: none), (pointer: coarse) {
    .more {
      opacity: 1;
    }
  }

  .editing {
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }

  .edit-wrap {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-width: 0;
  }

  .rename {
    width: 100%;
    min-width: 0;
    padding: 0.15rem 0.4rem;
    border: 1px solid var(--primary);
    border-radius: var(--shape-sm);
    background: var(--surface);
    color: var(--on-surface);
    font: inherit;
    font-size: var(--type-body-medium-size);
  }

  .rename[aria-invalid='true'] {
    border-color: var(--error);
  }

  .edit-error {
    margin-top: 0.15rem;
    color: var(--error);
    font-size: var(--type-label-medium-size);
  }

  .hint {
    padding-top: 0.2rem;
    padding-bottom: 0.2rem;
    border-radius: var(--shape-md);
    color: var(--on-surface-variant);
    font-size: var(--type-label-medium-size);
    font-style: italic;
  }

  .root-drop {
    position: sticky;
    bottom: 0.5rem;
    margin: 0 0.5rem;
    padding: 0.6rem 0.75rem;
    border: 1px dashed var(--outline);
    border-radius: var(--shape-md);
    background: var(--surface-container-high);
    color: var(--on-surface-variant);
    font-size: var(--type-body-medium-size);
    text-align: center;
  }

  .unpathed {
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px dashed var(--outline-variant);
  }

  .unpathed h3 {
    display: flex;
    gap: 0.4rem;
    align-items: baseline;
    margin: 0 0 0.15rem;
    padding: 0 0.5rem;
    border-radius: var(--shape-md);
    color: var(--on-surface-variant);
    font-size: var(--type-label-medium-size);
    font-style: italic;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .count {
    font-family: var(--mono);
    font-style: normal;
  }

  .empty {
    margin: 0;
    padding: 0 0.5rem;
    color: var(--on-surface-variant);
    font-size: 0.9rem;
  }

  /* The row menu: fixed, so the sidebar's own scrolling cannot clip it. */
  .menu {
    position: fixed;
    z-index: 50;
    min-width: 12rem;
    max-width: min(20rem, calc(100vw - 1rem));
    max-height: min(24rem, 60vh);
    overflow-y: auto;
    padding: 0.25rem 0;
    border-radius: var(--shape-md);
    background: var(--surface-container-high);
    box-shadow: var(--elevation-float);
    color: var(--on-surface);
  }

  .menu-heading {
    padding: 0.5rem 1rem 0.25rem;
    color: var(--on-surface-variant);
    font-size: var(--type-label-medium-size);
  }

  .menu-item {
    display: block;
    width: 100%;
    min-height: 2.5rem;
    padding: 0.5rem 1rem;
    overflow: hidden;
    border: 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    font-size: var(--type-body-medium-size);
    text-align: left;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .menu-item:hover,
  .menu-item:focus-visible {
    background: color-mix(in srgb, var(--on-surface) calc(var(--state-hover) * 100%), transparent);
    outline: none;
  }

  .menu-item:focus-visible {
    background: color-mix(in srgb, var(--on-surface) calc(var(--state-focus) * 100%), transparent);
  }

  .live {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }

  .toast-region {
    position: sticky;
    bottom: 0.5rem;
    z-index: 40;
    margin: auto 0.5rem 0;
  }

  .toast {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 0.6rem 0.75rem;
    border-radius: var(--shape-sm);
    background: var(--inverse-surface);
    box-shadow: var(--elevation-float);
    color: var(--inverse-on-surface);
    font-size: var(--type-body-small-size);
    line-height: 1.35;
  }

  .toast.bad {
    background: var(--error-container);
    color: var(--on-error-container);
  }

  .toast span {
    flex: 1;
    min-width: 0;
  }

  .toast-close {
    flex: none;
    padding: 0 0.25rem;
    border: 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    line-height: 1;
  }

  /* KAN-1818, compact: the list is its own full-width screen, so its controls and rows are touch
     targets (48px; the M3 minimum is 44). */
  @media (max-width: 599.98px) {
    .new-note,
    .new-folder,
    .search-input,
    .clear-search {
      min-height: 3rem;
      font-size: 1rem;
    }

    .new-folder {
      width: 3rem;
    }

    .row {
      display: flex;
      flex-direction: column;
      justify-content: center;
      min-height: 3rem;
      padding-right: 3.25rem;
    }

    /* `.row` centres its content (vertically, in a column); a folder row is a row, so the inherited
       `justify-content: center` would centre the name and caret horizontally. */
    .row.folder {
      flex-direction: row;
      align-items: center;
      justify-content: flex-start;
    }

    .row.editing {
      flex-direction: row;
      align-items: center;
    }

    .more {
      top: 0;
      right: 0.25rem;
      width: 2.75rem;
      height: 3rem;
      border-radius: var(--shape-md);
    }

    .menu-item {
      min-height: 3rem;
      font-size: 1rem;
    }

    .rename {
      min-height: 2.5rem;
      font-size: 1rem;
    }
  }
</style>
