# {
#   "Id": "8488b592-7a9f-40d9-b7d4-5cb4cd998c37",
#   "Name": "CareJobs.Now",
#   "Author": "CareJobs.Now",
#   "Version": "1.0.0",
#   "MinWoxVersion": "2.4.2",
#   "Runtime": "python",
#   "Description": "Search US healthcare jobs with the pay employers post (nurses, CNAs, techs, therapists)",
#   "Icon": "svg:<svg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 128 128'><rect width='128' height='128' rx='24' fill='#ffffff'/><path fill-rule='evenodd' fill='#C02E3B' d='M42.1 42.1A22 22 0 1 1 85.9 42.1A22 22 0 1 1 85.9 85.9A22 22 0 1 1 42.1 85.9A22 22 0 1 1 42.1 42.1Z'/></svg>",
#   "Website": "https://github.com/yumaheymans/Wox.Plugin.CareJobs",
#   "TriggerKeywords": ["cj"],
#   "SupportedOS": ["Windows", "Darwin", "Linux"],
#   "Features": [
#     { "Name": "debounce", "Params": { "IntervalMs": 300 } },
#     { "Name": "mru", "Params": { "HashBy": "identityKey" } }
#   ]
# }

"""
CareJobs.Now: single-file Wox SDK plugin (Python).

Type "cj icu nurse tx" to search free US healthcare job listings, with the pay
employers post. Only what you type is sent, to https://carejobs.now/api/mcp.
No account, no tracking. Standard library only (plus the wox_plugin SDK that
Wox's Python host provides).

Enter opens the job. The action panel also opens the employer's page on
CareJobs.Now. Recently opened jobs come back on the Wox start page (MRU).
"""

import asyncio
import dataclasses
import webbrowser

from wox_plugin import Context, MRUData, PluginInitParams, Query, QueryResponse, Result, ResultAction, WoxImage

USER_AGENT = "CareJobs-Wox-Plugin/1.0"

# ---------------------------------------------------------------------------
# CareJobs.Now core: query parsing, API call, result items. Standard library
# only. Everything above the launcher glue is plain functions so it can be
# tested without a launcher. Expects USER_AGENT to be defined before it.
# ---------------------------------------------------------------------------
import json
import re
import urllib.parse
import urllib.request

SITE_URL = "https://carejobs.now"
API_URL = SITE_URL + "/api/mcp"
TIMEOUT_SECONDS = 8
MAX_JOBS = 10
MAX_QUERY_CHARS = 200
MAX_BODY_BYTES = 2000000
HINT_TITLE = "Type a job and a state, e.g. icu nurse tx"
POPULAR_SEARCHES = ("registered nurse", "CNA", "LPN", "medical assistant", "travel nurse")

# The 50 states and DC: what the CareJobs.Now API accepts.
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
STATE_CODES_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}
# Two-letter job words that are also state codes: a lone "pa" or "ma" means
# physician assistant or medical assistant, not Pennsylvania or Massachusetts.
JOB_WORDS_THAT_LOOK_LIKE_STATES = ("PA", "MA")


def parse_query(text):
    """Split what the user typed into {"query", "state", "remote"}.

    "icu nurse tx" -> icu nurse / TX; "rn new york" -> rn / NY;
    "remote coding" -> coding / remote; a leading or trailing "in" is dropped.
    A two-letter word is a state only when it is the last word and a valid
    USPS code ("in" is never read as Indiana: it is the connector word, so type
    "indiana" for Indiana).
    """
    words = re.sub(r"[,;]+", " ", (text or "")[:MAX_QUERY_CHARS]).split()
    state = ""
    for size in (3, 2, 1):  # full state name at the end, longest first
        if len(words) >= size:
            code = STATE_CODES_BY_NAME.get(" ".join(words[-size:]).lower())
            if code:
                state = code
                del words[-size:]
                break
    if not state and words:
        last = words[-1].upper()
        lone_job_word = len(words) == 1 and last in JOB_WORDS_THAT_LOOK_LIKE_STATES
        if len(last) == 2 and last in US_STATES and last != "IN" and not lone_job_word:
            state = last
            words.pop()
    remote = any(word.lower() == "remote" for word in words)
    words = [word for word in words if word.lower() != "remote"]
    while words and words[0].lower() == "in":
        words.pop(0)
    while words and words[-1].lower() == "in":
        words.pop()
    return {"query": " ".join(words), "state": state, "remote": remote}


def board_url(parsed):
    """The CareJobs.Now board URL for the same search."""
    params = []
    if parsed["query"]:
        params.append(("q", parsed["query"]))
    if parsed["state"]:
        params.append(("state", parsed["state"]))
    if parsed["remote"]:
        params.append(("remote", "1"))
    if not params:
        return SITE_URL + "/"
    return SITE_URL + "/?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def short_pay(pay, employer=""):
    """One-line pay: keep the part before " (", and say "typical at <employer>"
    when the parenthesis says the figure is a typical range, not the posting's."""
    if not isinstance(pay, str) or not pay.strip():
        return ""
    head, separator, rest = pay.strip().partition(" (")
    head = head.strip()
    if separator and rest.lstrip().lower().startswith("typical"):
        return head + " typical at " + employer if employer else head + " typical"
    return head


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _web_url(value, fallback):
    """Only ever hand http(s) addresses to the browser."""
    value = _text(value)
    return value if urllib.parse.urlparse(value).scheme in ("http", "https") else fallback


def job_item(job):
    employer = _text(job.get("employer"))
    title = _text(job.get("title")) or "Healthcare job"
    listed = _text(job.get("listed"))
    parts = [short_pay(job.get("pay"), employer), _text(job.get("location")), "listed " + listed if listed else ""]
    url = _web_url(job.get("url"), SITE_URL + "/")
    employer_page = _web_url(job.get("employer_page"), "")
    return {
        "kind": "job",
        "title": title + " at " + employer if employer else title,
        "subtitle": " | ".join(part for part in parts if part),
        "url": url,
        "employer_page": employer_page,
    }


def hint_items():
    items = [{
        "kind": "hint",
        "title": HINT_TITLE,
        "subtitle": "Free US healthcare jobs with the pay employers post. Press Enter to open CareJobs.Now",
        "url": SITE_URL + "/",
        "employer_page": "",
    }]
    for term in POPULAR_SEARCHES:
        items.append({
            "kind": "popular",
            "title": "Search " + term,
            "subtitle": "Popular search on CareJobs.Now",
            "url": SITE_URL + "/?q=" + urllib.parse.quote(term),
            "employer_page": "",
        })
    return items


def error_item(parsed):
    return {
        "kind": "error",
        "title": "CareJobs.Now could not be reached",
        "subtitle": "Press Enter to search on CareJobs.Now in your browser",
        "url": board_url(parsed),
        "employer_page": "",
    }


def _structured_content(body):
    """The tool's structuredContent from a JSON (or event-stream) answer."""
    body = body.strip()
    if not body.startswith("{"):  # server-sent events: take the last data line
        data_lines = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
        body = data_lines[-1] if data_lines else ""
    result = json.loads(body).get("result")
    if not isinstance(result, dict) or result.get("isError"):
        raise ValueError("the search was refused")
    content = result.get("structuredContent")
    if not isinstance(content, dict):
        raise ValueError("the answer has no structuredContent")
    return content


def search_jobs(parsed, limit=MAX_JOBS):
    """Call search_healthcare_jobs on the live API. Raises on any failure."""
    arguments = {"limit": limit}
    if parsed["query"]:
        arguments["query"] = parsed["query"]
    if parsed["state"]:
        arguments["state"] = parsed["state"]
    if parsed["remote"]:
        arguments["remote"] = True
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search_healthcare_jobs", "arguments": arguments},
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return _structured_content(response.read(MAX_BODY_BYTES).decode("utf-8", "replace"))


def build_items(text, fetch=search_jobs):
    """What to show for the typed text: a list of plain item dicts. Never raises."""
    parsed = parse_query(text)
    if not (parsed["query"] or parsed["state"] or parsed["remote"]):
        return hint_items()
    try:
        content = fetch(parsed)
        jobs = [job for job in (content.get("jobs") or []) if isinstance(job, dict)][:MAX_JOBS]
        items = [job_item(job) for job in jobs]
        more = _web_url(content.get("more"), board_url(parsed))
        total = content.get("total")
        total = total if isinstance(total, int) and total >= len(items) else len(items)
    except Exception:
        return [error_item(parsed)]
    if not items:
        return [{
            "kind": "empty",
            "title": "No open jobs match this search yet",
            "subtitle": "Press Enter to try fewer words on CareJobs.Now",
            "url": more,
            "employer_page": "",
        }]
    items.append({
        "kind": "more",
        "title": "See all {:,} {} on CareJobs.Now".format(total, "job" if total == 1 else "jobs"),
        "subtitle": "Opens the same search on the board, with filters",
        "url": more,
        "employer_page": "",
    })
    return items
# ---------------------------------------------------------------------------
# End of core.
# ---------------------------------------------------------------------------


RESULT_ICON = WoxImage.new_svg(
    "<svg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 128 128'><rect width='128' height='128' rx='24' fill='#ffffff'/><path fill-rule='evenodd' fill='#C02E3B' d='M42.1 42.1A22 22 0 1 1 85.9 42.1A22 22 0 1 1 85.9 85.9A22 22 0 1 1 42.1 85.9A22 22 0 1 1 42.1 42.1Z'/></svg>"
)

# Bundled "open" verb from Wox's own action icon set (theme-adaptive).
OPEN_ICON = WoxImage.new_svg(
    "<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' "
    "stroke='var(--wox-theme-icon-color)' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
    "<path d='M14 5h5v5M19 5l-9 9'/><path d='M13 7H6a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-7'/></svg>"
)

# Kinds of result worth bringing back on the start page (MRU).
RESTORABLE_KINDS = ("job", "popular")

_RESULT_FIELDS = {field.name for field in dataclasses.fields(Result)}


def _identity(key):
    """identity_key on current Wox SDKs, score_key (its older name) on older ones."""
    return {"identity_key": key} if "identity_key" in _RESULT_FIELDS else {"score_key": key}


def _open(url):
    if urllib.parse.urlparse(str(url or "")).scheme in ("http", "https"):
        webbrowser.open(url)


class CareJobsPlugin:
    async def init(self, ctx: Context, params: PluginInitParams) -> None:
        self.api = params.api
        try:
            await self.api.on_mru_restore(ctx, self._restore)
        except Exception:  # an older Wox without MRU restore: the plugin still works
            pass

    async def query(self, ctx: Context, query: Query) -> QueryResponse:
        # Wox gives the text after "cj". Rejoin command + search in case Wox split off a first word.
        text = " ".join(part for part in (query.command, query.search) if part)
        try:
            # urllib blocks, so keep it off the host's event loop.
            items = await asyncio.get_running_loop().run_in_executor(None, build_items, text)
        except Exception:  # never crash the plugin host
            items = [error_item(parse_query(text))]
        return QueryResponse(results=[self._result(item, rank) for rank, item in enumerate(items)])

    def _result(self, item, rank):
        data = {"kind": item["kind"], "url": item["url"], "employer_page": item["employer_page"]}
        actions = [
            ResultAction(
                name="Open the job" if item["kind"] == "job" else "Open on CareJobs.Now",
                icon=OPEN_ICON,
                is_default=True,
                action=self._open_action,
                context_data=data,
            )
        ]
        if item["employer_page"]:
            actions.append(
                ResultAction(
                    name="Open the employer's page on CareJobs.Now",
                    icon=OPEN_ICON,
                    action=self._open_action,
                    context_data={"kind": "employer", "url": item["employer_page"], "employer_page": ""},
                )
            )
        extra = _identity(item["url"]) if item["kind"] in RESTORABLE_KINDS else {}
        return Result(
            title=item["title"],
            sub_title=item["subtitle"],
            icon=RESULT_ICON,
            score=100 - rank,  # keep the board's order
            actions=actions,
            **extra,
        )

    async def _open_action(self, ctx: Context, action_context) -> None:
        _open((action_context.context_data or {}).get("url"))

    async def _restore(self, ctx: Context, mru: MRUData):
        """Rebuild a start-page row from what was stored. No network, answers at once."""
        data = mru.context_data or {}
        if data.get("kind") not in RESTORABLE_KINDS or not data.get("url"):
            return None
        item = {
            "kind": data["kind"],
            "title": mru.title,
            "subtitle": mru.sub_title,
            "url": data["url"],
            "employer_page": data.get("employer_page", ""),
        }
        return self._result(item, 0)


# MUST HAVE: Wox loads the plugin object from this name.
plugin = CareJobsPlugin()
