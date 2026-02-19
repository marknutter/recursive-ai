"""RLM Memory TUI Dashboard.

Interactive terminal interface for browsing, searching, and managing
the RLM memory store. Built with textual.

Launch: `rlm tui` or `rlm-tui`
"""

from __future__ import annotations

import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from rlm import db, memory


# --- Helpers ---

def _fmt_size(chars: int) -> str:
    if chars < 1000:
        return f"{chars}"
    elif chars < 1_000_000:
        return f"{chars / 1000:.1f}K"
    else:
        return f"{chars / 1_000_000:.1f}M"


def _fmt_date(ts: float) -> str:
    if ts <= 0:
        return "—"
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _fmt_tags(tags: list) -> str:
    if not tags:
        return ""
    return ", ".join(tags[:4]) + ("..." if len(tags) > 4 else "")


# --- Delete Confirmation Modal ---

class ConfirmDeleteModal(ModalScreen[bool]):
    """Modal dialog to confirm entry deletion."""

    DEFAULT_CSS = """
    ConfirmDeleteModal {
        align: center middle;
    }
    #confirm-dialog {
        width: 60;
        height: auto;
        max-height: 12;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #confirm-dialog Static {
        width: 100%;
        margin-bottom: 1;
    }
    #confirm-buttons {
        width: 100%;
        height: 3;
        align: center middle;
    }
    #confirm-buttons Button {
        margin: 0 2;
    }
    """

    def __init__(self, entry_id: str, summary: str) -> None:
        super().__init__()
        self.entry_id = entry_id
        self.entry_summary = summary

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(f"Delete entry [b]{self.entry_id}[/b]?\n\n{self.entry_summary[:80]}")
            with Horizontal(id="confirm-buttons"):
                yield Button("Delete", variant="error", id="confirm-delete")
                yield Button("Cancel", variant="primary", id="cancel-delete")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-delete")


# --- Main App ---

class RlmTuiApp(App):
    """RLM Memory Dashboard."""

    TITLE = "RLM Memory Dashboard"

    CSS = """
    #browse-layout {
        height: 1fr;
    }
    #tags-sidebar {
        width: 28;
        height: 1fr;
        border-right: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    #tags-sidebar-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    .sidebar-section-title {
        text-style: bold;
        color: $accent;
        padding: 1 0 0 0;
    }
    #browse-main {
        height: 1fr;
    }
    #browse-table {
        height: 1fr;
    }
    #search-table {
        height: 1fr;
    }
    #browse-filter {
        dock: top;
        margin: 0 0 1 0;
    }
    #search-input {
        dock: top;
        margin: 0 0 1 0;
    }
    #detail-meta {
        dock: top;
        height: 3;
        padding: 0 1;
        background: $accent 10%;
    }
    #grep-bar {
        dock: top;
        height: 3;
    }
    #grep-input {
        width: 1fr;
    }
    #stats-body {
        padding: 1 2;
    }
    #browse-status {
        dock: bottom;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #search-status {
        dock: bottom;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("1", "switch_tab('browse')", "Browse", show=True),
        Binding("2", "switch_tab('search')", "Search", show=True),
        Binding("3", "switch_tab('detail')", "Detail", show=True),
        Binding("4", "switch_tab('stats')", "Stats", show=True),
        Binding("5", "switch_tab('tags')", "Tags", show=True),
        Binding("d", "delete_selected", "Delete", show=True),
        Binding("r", "refresh_panel", "Refresh", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._selected_entry_id: str | None = None
        self._current_search_query: str = ""
        self._browse_offset: int = 0
        self._browse_limit: int = 100
        self._browse_total: int = 0
        self._browse_tags: list[str] = []
        self._detail_content: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs"):
            # Browse tab
            with TabPane("Browse", id="browse"):
                with Horizontal(id="browse-layout"):
                    with VerticalScroll(id="tags-sidebar"):
                        yield Label("Tags", id="tags-sidebar-title")
                        yield Label("Recent (7d)", classes="sidebar-section-title")
                        yield ListView(id="sidebar-recent-list")
                        yield Label("Sessions", classes="sidebar-section-title")
                        yield ListView(id="sidebar-sessions-list")
                        yield Label("All Tags", classes="sidebar-section-title")
                        yield ListView(id="sidebar-all-list")
                    with Vertical(id="browse-main"):
                        yield Input(placeholder="Filter by tags (comma-separated)...", id="browse-filter")
                        yield DataTable(id="browse-table", cursor_type="row")
                        yield Static("", id="browse-status")

            # Search tab
            with TabPane("Search", id="search"):
                with Vertical():
                    yield Input(placeholder="Search memories...", id="search-input")
                    yield DataTable(id="search-table", cursor_type="row")
                    yield Static("", id="search-status")

            # Detail tab
            with TabPane("Detail", id="detail"):
                with Vertical():
                    yield Static("Select an entry from Browse or Search", id="detail-meta")
                    with Horizontal(id="grep-bar"):
                        yield Input(placeholder="Grep within entry...", id="grep-input")
                        yield Button("Grep", id="grep-btn")
                        yield Button("Clear", id="grep-clear-btn")
                    yield RichLog(id="detail-content", wrap=True, markup=True)

            # Stats tab
            with TabPane("Stats", id="stats"):
                with VerticalScroll():
                    yield Static("Loading stats...", id="stats-body")

            # Tags tab
            with TabPane("Tags", id="tags-tab"):
                yield DataTable(id="tags-table", cursor_type="row")

        yield Footer()

    def on_mount(self) -> None:
        memory.init_memory_store()
        self._setup_browse_table()
        self._setup_search_table()
        self._setup_tags_table()
        self._load_browse_data()
        self._load_sidebar_tags()
        self._load_tags_table()
        self._load_stats()

    # --- Table setup ---

    def _setup_browse_table(self) -> None:
        table = self.query_one("#browse-table", DataTable)
        table.add_columns("ID", "Summary", "Tags", "Size", "Date")

    def _setup_search_table(self) -> None:
        table = self.query_one("#search-table", DataTable)
        table.add_columns("Score", "ID", "Summary", "Tags", "Size")

    def _setup_tags_table(self) -> None:
        table = self.query_one("#tags-table", DataTable)
        table.add_columns("Tag", "Count")

    # --- Browse ---

    def _load_browse_data(self) -> None:
        table = self.query_one("#browse-table", DataTable)
        table.clear()
        tags = self._browse_tags if self._browse_tags else None
        entries, total = db.list_all_entries(
            tags=tags, offset=self._browse_offset, limit=self._browse_limit
        )
        self._browse_total = total
        for entry in entries:
            table.add_row(
                entry["id"],
                (entry.get("summary", "") or "")[:60],
                _fmt_tags(entry.get("tags", [])),
                _fmt_size(entry.get("char_count", 0)),
                _fmt_date(entry.get("timestamp", 0)),
                key=entry["id"],
            )
        status = self.query_one("#browse-status", Static)
        showing = len(entries)
        if tags:
            status.update(f"Showing {showing} of {total} entries (filtered by: {', '.join(self._browse_tags)})")
        else:
            status.update(f"Showing {showing} of {total} entries")

    def _load_sidebar_tags(self) -> None:
        # Recent tags (last 7 days)
        recent_list = self.query_one("#sidebar-recent-list", ListView)
        recent_list.clear()
        recent_tags = db.list_recent_tags(days=7)
        for tag, count in list(recent_tags.items())[:10]:
            recent_list.append(ListItem(Label(f"{tag} ({count})")))

        # Session tags (semantic/project tags from archived sessions)
        sessions_list = self.query_one("#sidebar-sessions-list", ListView)
        sessions_list.clear()
        session_tags = db.list_tags_for_tagged_entries("session", limit=10)
        for tag, count in session_tags.items():
            sessions_list.append(ListItem(Label(f"{tag} ({count})")))

        # All tags (top 10 by overall frequency)
        all_list = self.query_one("#sidebar-all-list", ListView)
        all_list.clear()
        all_tags = db.list_all_tags()
        for tag, count in list(all_tags.items())[:10]:
            all_list.append(ListItem(Label(f"{tag} ({count})")))

    # --- Search ---

    def _run_search(self, query: str) -> None:
        self._current_search_query = query
        table = self.query_one("#search-table", DataTable)
        table.clear()
        results = db.search_fts(query, max_results=50)
        for entry in results:
            table.add_row(
                f"{entry.get('score', 0):.1f}",
                entry["id"],
                (entry.get("summary", "") or "")[:50],
                _fmt_tags(entry.get("tags", [])),
                _fmt_size(entry.get("char_count", 0)),
                key=entry["id"],
            )
        status = self.query_one("#search-status", Static)
        status.update(f"{len(results)} results for \"{query}\"")

    # --- Detail ---

    def _load_detail(self, entry_id: str) -> None:
        self._selected_entry_id = entry_id
        entry = db.get_entry(entry_id)
        if entry is None:
            meta = self.query_one("#detail-meta", Static)
            meta.update(f"Entry {entry_id} not found")
            return

        meta = self.query_one("#detail-meta", Static)
        tags_str = ", ".join(entry.get("tags", []))
        size_str = _fmt_size(entry.get("char_count", 0))
        date_str = _fmt_date(entry.get("timestamp", 0))
        source = entry.get("source", "")
        meta.update(
            f"[b]{entry_id}[/b]  |  {size_str}  |  {date_str}  |  {source}\n"
            f"Tags: {tags_str}\n"
            f"Summary: {entry.get('summary', '')}"
        )

        content = entry.get("content", "")
        self._detail_content = content
        log = self.query_one("#detail-content", RichLog)
        log.clear()
        # For large entries, show first 10K chars
        if len(content) > 50_000:
            log.write(content[:10_000])
            log.write(f"\n\n--- Showing first 10K of {_fmt_size(len(content))} chars. Use grep to search. ---")
        else:
            log.write(content)

    # --- Stats ---

    def _load_stats(self) -> None:
        stats = db.get_stats()
        lines = []
        lines.append("[b]Memory Store Statistics[/b]\n")
        lines.append(f"  Total entries:  {stats['total_entries']:,}")
        lines.append(f"  Total chars:    {stats['total_chars']:,} ({_fmt_size(stats['total_chars'])})")
        lines.append(f"  Avg entry:      {stats['avg_chars']:,} chars")
        lines.append(f"  Smallest:       {stats['min_chars']:,} chars")
        lines.append(f"  Largest:        {stats['max_chars']:,} chars")
        lines.append(f"  DB file size:   {stats['db_file_size'] / 1_048_576:.1f} MB")

        if stats["oldest_timestamp"] > 0:
            oldest = _fmt_date(stats["oldest_timestamp"])
            newest = _fmt_date(stats["newest_timestamp"])
            lines.append(f"  Date range:     {oldest} — {newest}")

        lines.append("\n[b]Size Distribution[/b]")
        for label, count in stats["size_distribution"].items():
            bar = "█" * min(count // 2, 40)
            lines.append(f"  {label:20s} {count:4d}  {bar}")

        lines.append("\n[b]By Source[/b]")
        for source, info in stats["by_source"].items():
            lines.append(f"  {source:15s} {info['count']:4d} entries  {_fmt_size(info['chars'])} chars")

        lines.append(f"\n[b]Top Tags[/b] ({stats['unique_tags']} unique)")
        for tag, count in stats["top_tags"]:
            lines.append(f"  {tag:25s} {count:4d}")

        body = self.query_one("#stats-body", Static)
        body.update("\n".join(lines))

    # --- Tags tab ---

    def _load_tags_table(self) -> None:
        table = self.query_one("#tags-table", DataTable)
        table.clear()
        tag_counts = db.list_all_tags()
        for tag, count in tag_counts.items():
            table.add_row(tag, str(count), key=tag)

    # --- Event handlers ---

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "browse-filter":
            raw = event.value.strip()
            self._browse_tags = [t.strip() for t in raw.split(",") if t.strip()] if raw else []
            self._browse_offset = 0
            self._load_browse_data()
        elif event.input.id == "search-input":
            query = event.value.strip()
            if query:
                self._run_search(query)
        elif event.input.id == "grep-input":
            pattern = event.value.strip()
            if pattern and self._selected_entry_id:
                result = memory.grep_memory_content(self._selected_entry_id, pattern)
                log = self.query_one("#detail-content", RichLog)
                log.clear()
                log.write(result)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id
        entry_id = str(event.row_key.value)

        if table_id in ("browse-table", "search-table"):
            self._load_detail(entry_id)
            tabs = self.query_one("#tabs", TabbedContent)
            tabs.active = "detail"
            # Move focus to detail content so textual doesn't snap back
            # to the tab containing the previously-focused DataTable
            self.set_timer(0.05, lambda: self.query_one("#detail-content", RichLog).focus())
        elif table_id == "tags-table":
            # Click a tag → switch to Browse filtered by that tag
            tag = entry_id  # row key is the tag name
            filter_input = self.query_one("#browse-filter", Input)
            filter_input.value = tag
            self._browse_tags = [tag]
            self._browse_offset = 0
            self._load_browse_data()
            tabs = self.query_one("#tabs", TabbedContent)
            tabs.active = "browse"

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        sidebar_ids = {"sidebar-recent-list", "sidebar-sessions-list", "sidebar-all-list"}
        if event.list_view.id in sidebar_ids:
            label = event.item.query_one(Label)
            tag_text = str(label.content)
            # Extract tag name from "tag-name (N)" format
            tag = tag_text.rsplit(" (", 1)[0]
            filter_input = self.query_one("#browse-filter", Input)
            filter_input.value = tag
            self._browse_tags = [tag]
            self._browse_offset = 0
            self._load_browse_data()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "grep-btn":
            grep_input = self.query_one("#grep-input", Input)
            pattern = grep_input.value.strip()
            if pattern and self._selected_entry_id:
                result = memory.grep_memory_content(self._selected_entry_id, pattern)
                log = self.query_one("#detail-content", RichLog)
                log.clear()
                log.write(result)
        elif event.button.id == "grep-clear-btn":
            if self._detail_content:
                log = self.query_one("#detail-content", RichLog)
                log.clear()
                content = self._detail_content
                if len(content) > 50_000:
                    log.write(content[:10_000])
                    log.write(f"\n\n--- Showing first 10K of {_fmt_size(len(content))} chars ---")
                else:
                    log.write(content)
            grep_input = self.query_one("#grep-input", Input)
            grep_input.value = ""

    # --- Actions ---

    def action_switch_tab(self, tab_id: str) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        if tab_id == "tags":
            tabs.active = "tags-tab"
        else:
            tabs.active = tab_id

    def action_delete_selected(self) -> None:
        if not self._selected_entry_id:
            return
        entry = db.get_entry(self._selected_entry_id)
        summary = entry.get("summary", "") if entry else ""

        def handle_delete(confirmed: bool) -> None:
            if confirmed and self._selected_entry_id:
                db.delete_entry(self._selected_entry_id)
                self._selected_entry_id = None
                self._load_browse_data()
                self._load_sidebar_tags()
                self._load_tags_table()
                self._load_stats()

        self.push_screen(
            ConfirmDeleteModal(self._selected_entry_id, summary),
            handle_delete,
        )

    def action_refresh_panel(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        active = tabs.active
        if active == "browse":
            self._load_browse_data()
            self._load_sidebar_tags()
        elif active == "search":
            if self._current_search_query:
                self._run_search(self._current_search_query)
        elif active == "detail":
            if self._selected_entry_id:
                self._load_detail(self._selected_entry_id)
        elif active == "stats":
            self._load_stats()
        elif active == "tags-tab":
            self._load_tags_table()


def main():
    """Entry point for the rlm-tui console script."""
    memory.init_memory_store()
    app = RlmTuiApp()
    app.run()


if __name__ == "__main__":
    main()
