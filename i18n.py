"""Czech / English for the web UI.

Czech is the default; English is one click away through the switch in the
header, remembered in a cookie. The English text in the templates and in app.py
is the message id, and translations/cs_*.py map it to Czech - so a string with
no Czech entry yet still shows, in English, rather than breaking the page.

Templates mark text with {% trans %}...{% endtrans %} or {{ _("...") }}
(jinja2.ext.i18n, whitespace-trimmed, so a msgid is the text with runs of
whitespace collapsed to one space). Python code uses i18n._ and i18n.ngettext
the same way. Placeholders are %(name)s, filled after translation.
"""

import importlib
import pkgutil
import re

from flask import g, has_request_context, request

LANGS = ("cs", "en")
DEFAULT_LANG = "cs"
COOKIE = "lang"


def _load_catalog():
    """Merge every translations/cs_*.py CS dict into one."""
    import translations
    merged = {}
    for mod in pkgutil.iter_modules(translations.__path__):
        if mod.name.startswith("cs_"):
            merged.update(importlib.import_module(f"translations.{mod.name}").CS)
    return {" ".join(k.split()): v for k, v in merged.items()}


CS = _load_catalog()


def current_lang():
    if not has_request_context():
        return DEFAULT_LANG
    if "lang" not in g:
        want = request.args.get("lang") or request.cookies.get(COOKIE)
        g.lang = want if want in LANGS else DEFAULT_LANG
    return g.lang


def _(message, **params):
    text = message
    if current_lang() == "cs":
        text = CS.get(" ".join(message.split()), message)
    return text % params if params else text


def ngettext(singular, plural, n, **params):
    params.setdefault("num", n)
    if current_lang() == "cs":
        forms = CS.get(" ".join(singular.split()))
        if isinstance(forms, tuple):
            # Czech: 1 / 2-4 / 5+ (and 0)
            text = forms[0] if n == 1 else forms[1] if 2 <= n <= 4 else forms[2]
            return text % params
        if isinstance(forms, str):
            return forms % params
    return (singular if n == 1 else plural) % params


# -- dates ------------------------------------------------------------------

_CS_DAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]
_CS_DAYS_FULL = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]
_CS_MONTHS = ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář",
              "říj", "lis", "pro"]
_CS_MONTHS_FULL = ["leden", "únor", "březen", "duben", "květen", "červen",
                   "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]


def strftime(value, fmt):
    """datetime.strftime with Czech day and month names when Czech is on."""
    if current_lang() == "cs":
        fmt = re.sub(r"%([aAbB])", lambda m: {
            "a": _CS_DAYS[value.weekday()],
            "A": _CS_DAYS_FULL[value.weekday()],
            "b": _CS_MONTHS[value.month - 1],
            "B": _CS_MONTHS_FULL[value.month - 1],
        }[m.group(1)].replace("%", "%%"), fmt)
    return value.strftime(fmt)


def install(app):
    """Wire the translation functions into Jinja and add the switch route."""
    from flask import make_response, redirect, url_for
    from urllib.parse import urlsplit

    app.jinja_env.add_extension("jinja2.ext.i18n")
    app.jinja_env.policies["ext.i18n.trimmed"] = True
    app.jinja_env.install_gettext_callables(
        lambda s, **kw: _(s, **kw),
        lambda s, p, n, **kw: ngettext(s, p, n, **kw),
        newstyle=True)

    @app.context_processor
    def _lang_globals():
        return {"lang": current_lang(), "langs": LANGS}

    @app.route("/lang/<code>")
    def set_lang(code):
        # Back to the page the switch was clicked on - only a same-site path,
        # so the switch can never be used to bounce someone to another site.
        target = request.args.get("next") or ""
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or not target.startswith("/") \
                or target.startswith("//"):
            target = url_for("index")
        resp = make_response(redirect(target))
        if code in LANGS:
            resp.set_cookie(COOKIE, code, max_age=365 * 86400, samesite="Lax",
                            secure=request.is_secure, httponly=True)
        return resp
