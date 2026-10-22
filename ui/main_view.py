"""Main application shell: header with branding and navigation, welcome content, footer.

Navigation entries are visual placeholders in Stage 1; they are not wired to
any screens yet.
"""

from __future__ import annotations

from tkinter import ttk

from ui import styles

NAV_SECTIONS = ("Movies", "My Bookings", "My Profile")


class MainView(ttk.Frame):
    """Top-level frame that fills the root window."""

    def __init__(self, master, *, status_detail: str) -> None:
        super().__init__(master, style="App.TFrame")
        self._build_header()
        self._build_body(status_detail)
        self._build_footer()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Surface.TFrame", padding=(styles.SPACE_LG, styles.SPACE_MD))
        header.pack(fill="x")

        brand = ttk.Frame(header, style="Surface.TFrame")
        brand.pack(side="left")
        ttk.Label(brand, text="CINE", style="Brand.TLabel").pack(side="left")
        ttk.Label(brand, text="ROJO", style="BrandAccent.TLabel").pack(side="left")

        nav = ttk.Frame(header, style="Surface.TFrame")
        nav.pack(side="right")
        for name in NAV_SECTIONS:
            item = ttk.Frame(nav, style="Surface.TFrame")
            item.pack(side="left", padx=(styles.SPACE_LG, 0))
            ttk.Label(item, text=name, style="Nav.TLabel").pack(anchor="e")
            ttk.Label(item, text="coming soon", style="NavHint.TLabel").pack(anchor="e")

        # Thin red rule under the header.
        ttk.Frame(self, style="Accent.TFrame", height=3).pack(fill="x")

    def _build_body(self, status_detail: str) -> None:
        body = ttk.Frame(self, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL))
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=f"Welcome to {styles.APP_NAME}", style="Display.TLabel").pack(anchor="w")
        ttk.Label(body, text=styles.APP_TAGLINE, style="Tagline.TLabel").pack(
            anchor="w", pady=(styles.SPACE_XS, styles.SPACE_MD)
        )
        description = ttk.Label(
            body,
            text=(
                f"{styles.APP_NAME} is a desktop ticket booking system for browsing now-showing "
                "movies, choosing showtimes, reserving seats, and keeping track of your bookings "
                "and receipts — all stored locally on this computer."
            ),
            style="Body.TLabel",
            wraplength=720,
            justify="left",
        )
        description.pack(anchor="w")

        status = ttk.Frame(body, style="Panel.TFrame", padding=styles.SPACE_LG)
        status.pack(anchor="w", fill="x", pady=(styles.SPACE_XL, 0))
        ttk.Label(status, text="✓  Application foundation is ready", style="Status.TLabel").pack(
            anchor="w"
        )
        ttk.Label(status, text=status_detail, style="PanelBody.TLabel", wraplength=900,
                  justify="left").pack(anchor="w", pady=(styles.SPACE_SM, 0))

    def _build_footer(self) -> None:
        footer = ttk.Frame(self, style="Surface.TFrame", padding=(styles.SPACE_LG, styles.SPACE_SM))
        footer.pack(fill="x", side="bottom")
        ttk.Label(footer, text=f"© {styles.APP_NAME} · Sample data is fictional",
                  style="Footer.TLabel").pack(side="left")
        ttk.Label(footer, text="Stage 1 · Foundation", style="Footer.TLabel").pack(side="right")
