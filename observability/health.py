import time
from dataclasses import dataclass, field


@dataclass
class RunHealthCollector:
    run_id: str
    date: str
    stocks_collected: int = 0
    stocks_total: int = 0
    bvc_cached: bool = False
    news_articles: int = 0
    enrichers_ok: int = 0
    enrichers_total: int = 5
    reddit_ok: bool = False
    masi_rows: int = 0
    ai_ok: bool = False
    email_sent: bool = False
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._start: float = time.monotonic()

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def duration_s(self) -> int:
        return int(time.monotonic() - self._start)

    def to_log_line(self) -> str:
        mins, secs = divmod(self.duration_s, 60)
        sent = "✓" if self.email_sent else "✗"
        ai = "✓" if self.ai_ok else "✗"
        cached = " (cached)" if self.bvc_cached else ""
        return (
            f"Briefing complete | "
            f"stocks:{self.stocks_collected}/{self.stocks_total}{cached} "
            f"news:{self.news_articles} "
            f"enrichers:{self.enrichers_ok}/{self.enrichers_total} "
            f"ai:{ai} sent:{sent} "
            f"[{mins}m{secs:02d}s]"
        )

    def to_html_footer(self) -> str:
        mins, secs = divmod(self.duration_s, 60)

        def row(label: str, value: str, ok: bool = True, note: str = "") -> str:
            icon = "✓" if ok else "⚠"
            color = "#2d7a2d" if ok else "#b85c00"
            note_html = (
                f' <span style="color:#888;font-size:11px">{note}</span>' if note else ""
            )
            return (
                f"<tr>"
                f'<td style="padding:2px 12px 2px 0;color:#555">{label}</td>'
                f'<td style="padding:2px 12px 2px 0">{value}</td>'
                f'<td style="color:{color}">{icon}{note_html}</td>'
                f"</tr>"
            )

        warn_note = "; ".join(self.warnings)
        enricher_ok = self.enrichers_ok == self.enrichers_total
        cached_label = "Stocks collected (cached)" if self.bvc_cached else "Stocks collected"

        rows = "".join([
            row(cached_label, f"{self.stocks_collected} / {self.stocks_total}", self.stocks_collected > 0),
            row("News articles", str(self.news_articles), self.news_articles > 0),
            row(
                "Enrichers",
                f"{self.enrichers_ok} / {self.enrichers_total}",
                enricher_ok,
                warn_note if not enricher_ok else "",
            ),
            row("MASI history", f"{self.masi_rows} rows", self.masi_rows >= 5),
            row("AI analysis", "✓" if self.ai_ok else "unavailable", self.ai_ok),
            row("Email delivered", "✓" if self.email_sent else "failed", self.email_sent),
            row("Duration", f"{mins}m {secs:02d}s", True),
        ])

        return (
            '<hr style="margin-top:32px;border:none;border-top:1px solid #ddd">'
            f'<p style="font-family:monospace;font-size:12px;color:#888">'
            f"Run health &nbsp;·&nbsp; {self.date} &nbsp;·&nbsp; {self.run_id}"
            "</p>"
            '<table style="font-family:monospace;font-size:12px;border-collapse:collapse">'
            f"{rows}"
            "</table>"
        )
